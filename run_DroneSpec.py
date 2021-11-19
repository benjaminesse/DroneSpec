import os
import sys
import utm
import time
import yaml
import serial
import logging
import numpy as np
from datetime import datetime
import serial.tools.list_ports
from multiprocessing import Process, Queue

from ifit.spectrometers import Spectrometer
from ifit.gps import GPS
from ifit.load_spectra import read_spectrum
from ifit.parameters import Parameters
from ifit.spectral_analysis import Analyser


def analyse_spec(spec_fname, analyser, fpath, q):
    """."""
    # Read in the spectrum
    x, y, info, err = read_spectrum(spec_fname, spec_type='iFit')

    # Fit the spectrum
    fit = analyser.fit_spectrum(spectrum=[x, y],
                                update_params=True,
                                resid_limit=20,
                                int_limit=[0, 60000],
                                interp_method='linear')

    # Convert lat/lon to UTM
    utm_coords = utm.from_latlon(info['lat'], info['lon'])

    # Colate results and add to the queue
    conv = 2.54e15
    res = [info['timestamp'], info['lat'], info['lon'], info['alt'],
           utm_coords[0], utm_coords[1], utm_coords[2], utm_coords[3],
           fit.params['SO2'].fit_val, fit.params['SO2'].fit_err,
           fit.params['SO2'].fit_val/conv, fit.params['SO2'].fit_err/conv,
           info['integration_time'], np.max(fit.spec)]

    head, tail = os.path.split(spec_fname)
    meas_fname = f"{head}/meas/{tail.replace('spectrum', 'meas')}"

    with open(meas_fname, 'w') as w:
        for r in res:
            w.write(f'{r},')
    q.put(res)


def listener(q, save_fname):
    """."""
    # Handle writing the results file
    with open(save_fname, 'w') as w:

        # Write the header
        h = 'Time,Lat,Lon,Alt,X,Y,ZoneNum,ZoneLett,SO2_SCD_mol,SO2_err_mol,' \
            + 'SO2_SCD_ppmm,SO2_err_ppmm,IntegrationTime,Intensity'
        w.write(h + '\n')
        print('Time\tLat\tLon\tAlt\tSO2_SCD_ppmm\tSO2_err_ppmm')

        while True:
            # Unpack the results
            res = q.get()
            if res == 'kill':
                break
            else:
                msg = str(res[0])
                for r in res[1:]:
                    msg += f',{r}'
                w.write(msg + '\n')
                w.flush()
                print(f'{res[0]}\t{res[1]}\t{res[2]}\t{res[3]}\t{res[10]}\t'
                      + f'{res[11]}')


# =============================================================================
# Run main script
# =============================================================================

def run():

    # Get the logger
    logger = logging.getLogger()

    # Setup logger to standard output
    logger.setLevel(logging.INFO)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_formatter = logging.Formatter(
        '%(asctime)s - %(message)s', '%H:%M:%S')
    stdout_handler.setFormatter(stdout_formatter)
    logger.addHandler(stdout_handler)

    # Read in settings
    default_config = {'TargetIntensity': 50000,
                      'MinIntTime': 50,
                      'MaxIntTime': 300,
                      'IntTimeStep': 10,
                      'GPSCOMPORT': 0,
                      'FitWindow': [310, 320]}
    try:
        with open('bin/dronespec_settings.yml', 'r') as ymlfile:
            load_config = yaml.load(ymlfile, Loader=yaml.FullLoader)
            config = {**default_config, **load_config}
    except FileNotFoundError:
        config = default_config

    # Set the target intensity
    target_int = config['TargetIntensity']

    # Construct an array of intergration times
    int_times = np.arange(config['MinIntTime'],
                          config['MaxIntTime'] + config['IntTimeStep'],
                          config['IntTimeStep'])

    # Connect to the spectrometer
    spectro = Spectrometer()

    # Connect to the GPS
    ports = serial.tools.list_ports.comports()
    gps = GPS(ports[config['GPSCOMPort']].device)

    # Get the timestamp
    nowtime = datetime.strftime(datetime.now(), '%Y%m%d_%H%M%S')

    # Create the results folder
    fpath = f'Results/{nowtime}'
    if not os.path.isdir(fpath):
        os.makedirs(fpath)

    if not os.path.isdir(f'{fpath}/meas'):
        os.makedirs(f'{fpath}/meas')

    # Add file handler to logger
    f_handler = logging.FileHandler(f'{fpath}/log.txt')
    f_handler.setLevel(logging.INFO)
    f_formatter = logging.Formatter('%(asctime)s - %(message)s', '%H:%M:%S')
    f_handler.setFormatter(f_formatter)
    logger.addHandler(f_handler)

    # Initialise a process list
    processes = []

# =============================================================================
#   Set up iFit analyser
# =============================================================================

    # Create parameter dictionary
    params = Parameters()

    # Add the gases
    params.add('SO2',  value=1.0e16, vary=True, xpath='Ref/SO2_295K.txt')
    params.add('O3',   value=1.0e19, vary=True, xpath='Ref/O3_243K.txt')
    params.add('Ring', value=0.1,    vary=True, xpath='Ref/Ring.txt')

    # Add background polynomial parameters
    params.add('bg_poly0', value=0.0, vary=True)
    params.add('bg_poly1', value=0.0, vary=True)
    params.add('bg_poly2', value=0.0, vary=True)
    params.add('bg_poly3', value=1.0, vary=True)

    # Add intensity offset parameters
    params.add('offset0', value=0.0, vary=True)

    # Add wavelength shift parameters
    params.add('shift0', value=0.0, vary=True)
    params.add('shift1', value=0.1, vary=True)

    # Generate the analyser
    analyser = Analyser(params,
                        fit_window=config['FitWindow'],
                        frs_path='Ref/sao2010.txt',
                        model_padding=1.0,
                        model_spacing=0.01,
                        flat_flag=False,
                        stray_flag=True,
                        stray_window=[280, 290],
                        ils_type='Params',
                        ils_path=f'Spec/{spectro.serial_number}_ils.txt')

    # Report fitting parameters
    logger.info(params.pretty_print(cols=['name', 'value', 'vary', 'xpath']))

    # Initialise a counter
    i = 0

    # Generate the writing queue
    save_fname = f'{fpath}/so2_output.csv'
    q = Queue()
    listen = Process(target=listener, args=[q, save_fname])
    listen.daemon = True
    listen.start()

    # Start switched OFF
    control_file = '/home/pi/drone/bin/controlON'
    if os.path.isfile(control_file):
        os.remove(control_file)

    logger.info('PiSpec ready!')

    while True:

        # Get the status
        if not os.path.isfile(control_file):
            time.sleep(1)
            continue

        try:

            # Format the spectrum name and read
            spec_fname = f'{fpath}/spectrum_{i:05d}.txt'
            [x, y], info = spectro.get_spectrum(spec_fname, gps=gps)

            # Find the maximum intensity
            max_int = np.max(y)

            # Scale the intensity to the target
            scale = target_int / max_int

            # Scale the integration time by this factor
            int_time = spectro.integration_time * scale

            # Find the nearest value
            diff = ((int_times - int_time)**2)**0.5
            idx = np.where(diff == min(diff))[0][0]
            new_int_time = int(int_times[idx])

            # Update the integration time
            if new_int_time != spectro.integration_time:
                spectro.update_integration_time(new_int_time)

            # Clear any finished processes from the processes list
            processes = [p for p in processes if p.is_alive()]

            if len(processes) < 3:

                # Create new process to handle fitting of the last scan
                p = Process(target=analyse_spec,
                            args=[spec_fname, analyser, fpath, q])

                # Add to array of active processes
                processes.append(p)

                # Begin the process
                p.start()

            else:
                # Log that the process was not started
                logger.warning('Too many processes! Spectrum {i} not analysed')

            i += 1

        except KeyboardInterrupt:
            q.put('kill')
            break

    logger.info('Program ended')

    # Complete processes
    listen.join()
    for p in processes:
        p.join()


if __name__ == '__main__':
    run()
