"""Control script for the DronePi user inerface."""
import sys
import yaml
import time
import logging
import traceback
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor
from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal
from PyQt5.QtWidgets import (QMainWindow, QApplication, QWidget, QGridLayout,
                             QScrollArea, QSplitter, QLabel, QLineEdit,
                             QPushButton, QPlainTextEdit)

from ifit.pispec import PiSpec
from ifit.gui_functions import Widgets


logger = logging.getLogger()


COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b',
          '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']


class MainWindow(QMainWindow):
    """View for the iFit GUI."""

    def __init__(self):
        """View initialiser."""
        super().__init__()

        # Set the window properties
        self.statusBar().showMessage('Ready')
        self.setGeometry(40, 40, 700, 400)
        self.setWindowIcon(QIcon('bin/icons/main.ico'))

        self.widgets = Widgets()

        # Set the window layout
        self.generalLayout = QGridLayout()
        self._centralWidget = QScrollArea()
        self.widget = QWidget()
        self.setCentralWidget(self._centralWidget)
        self.widget.setLayout(self.generalLayout)

        # Scroll Area Properties
        self._centralWidget.setWidgetResizable(True)
        self._centralWidget.setWidget(self.widget)
        self.controlFrame = QWidget()
        self.graphFrame = QWidget()
        self.logFrame = QWidget()

        splitter1 = QSplitter(Qt.Horizontal)
        splitter2 = QSplitter(Qt.Vertical)
        splitter1.addWidget(self.controlFrame)
        splitter1.addWidget(self.graphFrame)

        splitter2.addWidget(splitter1)
        splitter2.addWidget(self.logFrame)

        self.generalLayout.addWidget(splitter2)

        self.connection_flag = False

        self._createApp()
        self.changeThemeDark()

        self.load_config()

    def _createApp(self):
        control_layout = QGridLayout(self.controlFrame)
        control_layout.setAlignment(Qt.AlignTop)
        nrow = 0

        # Add an input for the connection IP
        control_layout.addWidget(QLabel('IP Address:'), nrow, 0)
        self.widgets['ipaddress'] = QLineEdit()
        control_layout.addWidget(self.widgets['ipaddress'], nrow, 1)
        nrow += 1

        # Add an input for the connection username
        control_layout.addWidget(QLabel('Username:'), nrow, 0)
        self.widgets['username'] = QLineEdit()
        control_layout.addWidget(self.widgets['username'], nrow, 1)
        nrow += 1

        # Add an input for the connection password
        control_layout.addWidget(QLabel('Password:'), nrow, 0)
        self.widgets['password'] = QLineEdit()
        control_layout.addWidget(self.widgets['password'], nrow, 1)
        nrow += 1

        # Add a button to connect
        self.connect_btn = QPushButton('Connect!')
        self.connect_btn.clicked.connect(self.connect_pispec)
        control_layout.addWidget(self.connect_btn, nrow, 0, 1, 2)
        nrow += 1

        # Add a button to start and stop
        self.go_btn = QPushButton('Start!')
        self.go_btn.clicked.connect(self.start_stop_pispec)
        self.go_btn.setEnabled(False)
        control_layout.addWidget(self.go_btn, nrow, 0, 1, 2)
        nrow += 1

        # Add an input for the connection password
        control_layout.addWidget(QLabel('Volcano\nLatitude:'), nrow, 0)
        self.widgets['vlat'] = QLineEdit()
        control_layout.addWidget(self.widgets['vlat'], nrow, 1)
        nrow += 1

        # Add an input for the connection password
        control_layout.addWidget(QLabel('Volcano\nLongitude:'), nrow, 0)
        self.widgets['vlon'] = QLineEdit()
        control_layout.addWidget(self.widgets['vlon'], nrow, 1)
        nrow += 1

        # Add an input for the connection password
        control_layout.addWidget(QLabel('Volcano\nAltitude:'), nrow, 0)
        self.widgets['valt'] = QLineEdit()
        control_layout.addWidget(self.widgets['valt'], nrow, 1)
        nrow += 1

        # Create a textbox to display the program logs
        self.logBox = QTextEditLogger(self)
        fmt = logging.Formatter('%(asctime)s - %(message)s', '%H:%M:%S')
        self.logBox.setFormatter(fmt)
        logger.addHandler(self.logBox)
        logger.setLevel(logging.INFO)
        control_layout.addWidget(self.logBox.widget, nrow, 0, 1, 2)
        msg = 'Welcome to DroneSpec!'
        self.logBox.widget.appendPlainText(msg)

        log_layout = QGridLayout(self.logFrame)

        self.log = QPlainTextEdit(self.logFrame)
        self.log.setReadOnly(True)
        self.log.setFont(QFont('Courier', 10))
        log_layout.addWidget(self.log, 0, 0)

        self.graphwin = pg.GraphicsLayoutWidget(show=True)
        x_axis = pg.DateAxisItem(utcOffset=0)
        self.graphAx = self.graphwin.addPlot(row=0, col=0,
                                             axisItems={'bottom': x_axis})
        self.mapAx = self.graphwin.addPlot(row=0, col=1)
        self.mapAx.setAspectLocked(True)

        # Add plots
        self.graphPlot = pg.PlotCurveItem(pen=pg.mkPen(COLORS[0]))
        self.graphAx.addItem(self.graphPlot)
        self.mapPlot = pg.PlotCurveItem(pen=pg.mkPen(COLORS[2]))
        self.mapScatter = pg.ScatterPlotItem()
        self.mapAx.addItem(self.mapScatter)
        self.volcPlot = pg.ScatterPlotItem(size=15, pen=pg.mkPen(COLORS[7]),
                                           brush=pg.mkBrush(COLORS[3]))
        self.mapAx.addItem(self.volcPlot)

        # Generate the colorbar
        self.cmap = pg.colormap.get('magma')
        im = pg.ImageItem()
        self.so2_data = []
        self.cbar = pg.ColorBarItem(values=(0, 100), colorMap=self.cmap)
        self.cbar.setImageItem(im)
        self.cbar.sigLevelsChangeFinished.connect(self._update_map_colors)
        self.graphwin.addItem(self.cbar, 0, 2)

        # Add axis labels
        self.mapAx.setLabel('left', 'Latitude [deg]')
        self.mapAx.setLabel('bottom', 'Longitude [deg]')
        self.graphAx.setLabel('left', 'SO2 SCD [ppm.m]')
        self.graphAx.setLabel('bottom', 'Time [UTC]')

        # Add the plots to the layout
        output_layout = QGridLayout(self.graphFrame)
        output_layout.addWidget(self.graphwin, 0, 0)

        # Connect changes in the volcano location to the plot
        self.widgets['vlat'].textChanged.connect(self.update_map)
        self.widgets['vlon'].textChanged.connect(self.update_map)

    def update_map(self):
        """Update the volcano location."""
        try:
            x = float(self.widgets.get('vlon'))
            y = float(self.widgets.get('vlat'))
            self.volcPlot.setData([x], [y])
        except ValueError:
            pass

    def connect_pispec(self):
        """Connect to the PiSpec."""
        if not self.connection_flag:
            self.connect_btn.setEnabled(False)
            self.update_status('Connecting...')
            host = self.widgets.get('ipaddress')
            user = self.widgets.get('username')
            password = self.widgets.get('password')
            self.pispec = PiSpec(host, user, password)
            self.update_status('Ready')

            self.connection_flag = True
            self.connect_btn.setEnabled(True)
            self.go_btn.setEnabled(True)
            self.connect_btn.setText('Disconnect!')

            # Begine the syncing
            self.sync_pispec()

        else:
            self.connect_btn.setEnabled(False)
            self.syncWorker.stop()
            self.syncThread.quit()
            self.syncThread.wait()
            self.pispec.disconnect()
            self.connection_flag = False
            self.connect_btn.setEnabled(True)
            self.go_btn.setEnabled(False)
            self.connect_btn.setText('Connect!')

    def start_stop_pispec(self):
        """Toggle if the PiSpec is active."""
        if self.pispec.is_active:
            self.pispec.send_stop()
            self.go_btn.setText('Start!')
            logger.info('PiSpec Stopped')
        else:
            self.pispec.send_start()
            self.go_btn.setText('Stop!')
            logger.info('PiSpec Started')

    def sync_pispec(self):
        """Pull data from the PiSpec."""
        # Initialise the sync thread
        self.syncThread = QThread()
        self.syncWorker = SyncWorker(self.pispec)

        # Move the worker to the thread
        self.syncWorker.moveToThread(self.syncThread)

        # Connect the signals
        self.syncThread.started.connect(self.syncWorker.run)
        self.syncWorker.finished.connect(self.sync_finished)
        self.syncWorker.error.connect(self.update_error)
        self.syncWorker.updateLog.connect(self.update_log)
        self.syncWorker.updateStatus.connect(self.update_status)
        self.syncWorker.updatePlots.connect(self.update_plots)
        self.syncWorker.finished.connect(self.syncThread.quit)

        # Start the worker
        self.syncThread.start()

    def update_plots(self, plot_data):
        """Update data plots."""
        # Unpack the data
        timestamp, lat, lon, so2_scd = plot_data

        # Add the so2 data
        self.so2_data = so2_scd

        # Update plots
        self.graphPlot.setData(x=timestamp, y=so2_scd)

        # Get the colormap limits
        map_lo_lim, map_hi_lim = self.cbar.levels()

        # Normalise the data and convert to colors
        norm_values = (self.so2_data - map_lo_lim) / (map_hi_lim - map_lo_lim)
        np.nan_to_num(norm_values, copy=False)
        pens = [pg.mkPen(color=self.cmap.map(val)) for val in norm_values]
        brushes = [pg.mkBrush(color=self.cmap.map(val)) for val in norm_values]

        # Update map plots
        self.mapPlot.setData(x=lon, y=lat)
        self.mapScatter.setData(x=lon, y=lat, pen=pens, brush=brushes)

    def _update_map_colors(self):
        try:
            lon, lat = self.mapScatter.getData()
            so2_data = self.so2_data

            # Get the colormap limits
            map_lo_lim, map_hi_lim = self.cbar.levels()

            # Normalise the data and convert to colors
            norm_values = (so2_data - map_lo_lim) / (map_hi_lim - map_lo_lim)
            np.nan_to_num(norm_values, copy=False)

            pens = [pg.mkPen(color=self.cmap.map(val)) for val in norm_values]
            brushes = [pg.mkBrush(color=self.cmap.map(val))
                       for val in norm_values]

            self.mapScatter.setData(x=lon, y=lat, pen=pens, brush=brushes)
        except ValueError:
            pass

    def sync_finished(self):
        """Finished signal."""
        self.update_status('Ready')

    def update_log(self, log_text):
        """Update logs from PiSpec."""
        text = self.log.toPlainText().split('\n')
        for line in log_text[len(text):]:
            self.log.appendPlainText(line.strip())

    def update_status(self, status):
        """Update GUI status."""
        self.statusBar().showMessage(status)

    def update_error(self, error):
        """Slot to update error messages from the worker."""
        exctype, value, trace = error
        logger.warning(f'Uncaught exception!\n{trace}')

    def changeThemeDark(self):
        """Change theme to dark."""
        darkpalette = QPalette()
        darkpalette.setColor(QPalette.Window, QColor(53, 53, 53))
        darkpalette.setColor(QPalette.WindowText, Qt.white)
        darkpalette.setColor(QPalette.Base, QColor(25, 25, 25))
        darkpalette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        darkpalette.setColor(QPalette.ToolTipBase, Qt.black)
        darkpalette.setColor(QPalette.ToolTipText, Qt.white)
        darkpalette.setColor(QPalette.Text, Qt.white)
        darkpalette.setColor(QPalette.Button, QColor(53, 53, 53))
        darkpalette.setColor(QPalette.Active, QPalette.Button,
                             QColor(53, 53, 53))
        darkpalette.setColor(QPalette.ButtonText, Qt.white)
        darkpalette.setColor(QPalette.BrightText, Qt.red)
        darkpalette.setColor(QPalette.Link, QColor(42, 130, 218))
        darkpalette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        darkpalette.setColor(QPalette.HighlightedText, Qt.black)
        darkpalette.setColor(QPalette.Disabled, QPalette.ButtonText,
                             Qt.darkGray)
        QApplication.instance().setPalette(darkpalette)

        pen = pg.mkPen('w', width=1.5)

        self.graphwin.setBackground('k')
        for ax in [self.graphAx, self.mapAx]:
            ax.getAxis('left').setPen(pen)
            ax.getAxis('right').setPen(pen)
            ax.getAxis('top').setPen(pen)
            ax.getAxis('bottom').setPen(pen)
            ax.getAxis('left').setTextPen(pen)
            ax.getAxis('bottom').setTextPen(pen)

    def closeEvent(self, event):
        """Handle GUI closure."""
        config = {}
        for key in self.widgets:
            config[key] = self.widgets.get(key)

        # Write the config
        with open('bin/.config.yml', 'w') as outfile:
            yaml.dump(config, outfile)

        try:
            self.syncWorker.stop()
            self.syncThread.quit()
            self.syncThread.wait()
            self.pispec.disconnect()
        except AttributeError:
            pass

    def load_config(self):
        """Load previous config."""
        try:
            with open('bin/.config.yml', 'r') as ymlfile:
                config = yaml.load(ymlfile, Loader=yaml.FullLoader)

            for key, item in config.items():
                try:
                    self.widgets.set(key, item)
                except Exception:
                    logger.warning(f'Failed to load {key} from config file')
        except FileNotFoundError:
            logger.warning('Unable to load config file!')


class SyncWorker(QObject):
    """Handle station syncing."""

    # Define signals
    error = pyqtSignal(tuple)
    finished = pyqtSignal()
    updateLog = pyqtSignal(list)
    updatePlots = pyqtSignal(list)
    updateStatus = pyqtSignal(str)

    def __init__(self, pispec):
        """Initialise."""
        super(QObject, self).__init__()
        self.pispec = pispec
        self.is_stopped = False

    def run(self):
        """Launch worker task."""
        try:
            self._run()
        except Exception:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.error.emit((exctype, value, traceback.format_exc()))
        self.finished.emit()

    def stop(self):
        """Stop the worker."""
        self.is_stopped = True

    def _run(self):
        """Worker task."""
        while not self.is_stopped:

            # Update status
            self.updateStatus.emit('Working...')

            # Pull PiSpec logs
            self.pispec.pull_log()
            with open(f'Results/{self.pispec.folder}/log.txt', 'r') as r:
                log_text = r.readlines()
            self.updateLog.emit(log_text)

            # Update so2 results
            update_flag = self.pispec.sync_so2_data()

            if update_flag:
                try:
                    fname = f'Results/{self.pispec.folder}/so2_output.csv'
                    df = pd.read_csv(fname, parse_dates=['Time'])

                    dt = pd.Timedelta('1s')
                    tstamp = np.array(
                        (df['Time'] - pd.Timestamp('1970-01-01')) // dt)
                    lat = df['Lat'].to_numpy()
                    lon = df['Lon'].to_numpy()
                    so2 = df['SO2_SCD_ppmm'].to_numpy()

                    # Send signal to plotter
                    self.updatePlots.emit([tstamp, lat, lon, so2])

                except pd.errors.EmptyDataError:
                    pass

            # Update status
            self.updateStatus.emit('Done')

            time.sleep(1)


# =============================================================================
# Logging text box
# =============================================================================

class QTextEditLogger(logging.Handler, QObject):
    """Record logs to the GUI."""

    appendPlainText = pyqtSignal(str)

    def __init__(self, parent):
        """Initialise."""
        super().__init__()
        QObject.__init__(self)
        self.widget = QPlainTextEdit(parent)
        self.widget.setReadOnly(True)
        self.widget.setFont(QFont('Courier', 10))
        self.appendPlainText.connect(self.widget.appendPlainText)

    def emit(self, record):
        """Emit the log."""
        msg = self.format(record)
        self.appendPlainText.emit(msg)


# Cliet Code
def main():
    """Run main function."""
    # Create an instance of QApplication
    app = QApplication(sys.argv)

    app.setStyle("Fusion")

    # Show the GUI
    view = MainWindow()
    view.show()

    # Execute the main loop
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
