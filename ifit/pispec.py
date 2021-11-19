import os
import logging
from pssh.clients import SSHClient

logger = logging.getLogger(__name__)

logging.getLogger('pssh').setLevel('WARNING')


class PiSpec():
    """."""

    def __init__(self, host, user, password):
        """Initialise."""
        self.host = host
        self.user = user
        self.password = password
        self.connect()

        # Make sure to start turned off
        self.send_stop()

        # Get the current folder
        output = self.client.run_command('ls /home/pi/drone/Results/')
        self.folder = [f for f in output.stdout][-1]

        logger.info(f'Watching directory {self.folder}')

        if not os.path.isdir(f'Results/{self.folder}'):
            os.makedirs(f'Results/{self.folder}')

    def send_start(self):
        """Send signal to start PiSpec."""
        self.client.run_command('touch /home/pi/drone/bin/controlON')
        self.is_active = True

    def send_stop(self):
        """Send signal to stop PiSpec."""
        self.client.run_command('rm /home/pi/drone/bin/controlON')
        self.is_active = False

    def copy_so2_data(self):
        """Update so2 results file."""
        # Set up local folder
        loc_folder = f'Results/{self.folder}'
        if not os.path.isdir(loc_folder):
            os.makedirs(loc_folder)

        self.client.copy_remote_file(
            f'/home/pi/drone/Results/{self.folder}/so2_output.csv',
            f'{loc_folder}/so2_output.csv')

    def sync_so2_data(self, buffer_len=100):
        """."""
        loc_file = f'Results/{self.folder}/so2_output.csv'
        try:
            with open(loc_file, 'r') as r:
                loc_lines = [line.strip() for line in r.readlines()]
        except FileNotFoundError:
            self.copy_so2_data()
            return True

        rem_file = f'/home/pi/drone/Results/{self.folder}/so2_output.csv'
        cmd = f'tail -n {int(buffer_len)} {rem_file}'
        output = self.client.run_command(cmd)
        rem_lines = [line.strip() for line in output.stdout]

        updated_flag = False
        with open(loc_file, 'a') as w:
            for line in rem_lines:
                if line not in loc_lines:
                    updated_flag = True
                    w.write(line + '\n')

        return updated_flag

    def sync_results(self):
        """Check for new measurement results."""
        # Set up local folder
        loc_folder = f'Results/{self.folder}/meas'
        if not os.path.isdir(loc_folder):
            os.makedirs(loc_folder)

        # Get remote files
        output = self.client.run_command(
            f'ls /home/pi/drone/Results/{self.folder}/meas/meas*')
        rem_files = [os.path.split(f)[1] for f in output.stdout]

        # Get local files
        loc_files = os.listdir(loc_folder)

        # Find remote files missing from local files
        files_to_sync = [f for f in rem_files if f not in loc_files]
        synced_files = []

        # Pull any missing files
        for file in files_to_sync:
            try:
                self.client.copy_remote_file(
                    f'/home/pi/drone/Results/{self.folder}/meas/{file}',
                    f'{loc_folder}/{file}')
                synced_files.append(f'{loc_folder}/{file}')
            except Exception:
                pass

        return synced_files

    def sync_spectra(self):
        """Check for new spectra files."""

        # Set up local folder
        loc_folder = f'Results/{self.folder}/'
        if not os.path.isdir(loc_folder):
            os.makedirs(loc_folder)

        # Get remote files
        output = self.client.run_command(
            f'ls /home/pi/drone/Results/{self.folder}/spectrum*')
        rem_files = [os.path.split(f)[1] for f in output.stdout]

        # Get local files
        loc_files = os.listdir(loc_folder)

        # Find remote files missing from local files
        files_to_sync = [f for f in rem_files if f not in loc_files]

        # Pull any missing files
        for file in files_to_sync:
            self.client.copy_remote_file(
                f'/home/pi/drone/Results/{self.folder}/{file}',
                f'{loc_folder}/{file}')

        return files_to_sync

    def pull_log(self):
        """Pull PiSpec logs."""
        self.client.copy_remote_file(
            f'/home/pi/drone/Results/{self.folder}/log.txt',
            f'Results/{self.folder}/log.txt')

    def connect(self):
        """Connect the session."""
        self.client = SSHClient(self.host, self.user, self.password)
        logger.info(f'Connected to {self.user}@{self.host}')

    def disconnect(self):
        """Disconnect the session."""
        try:
            self.client.disconnect()
            logger.info(f'{self.user}@{self.host} disconnected')
        except AttributeError:
            logger.warning('PiSpec not connected!')
