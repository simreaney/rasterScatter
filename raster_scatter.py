import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction


from .raster_scatter_dialog import RasterScatterDialog


class RasterScatterPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None

    def initGui(self):
        icon = QIcon(os.path.join(self.plugin_dir, "icon.svg"))
        self.action = QAction(icon, "Raster Scatter Plot", self.iface.mainWindow())
        self.action.triggered.connect(self.show_dialog)
        self.iface.addPluginToMenu("Raster Scatter Plot", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu("Raster Scatter Plot", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None

    def show_dialog(self):
        if self.dialog is None:
            self.dialog = RasterScatterDialog(self.iface)

        self.dialog.refresh_layers()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
