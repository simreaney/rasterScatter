def classFactory(iface):
    from .raster_scatter import RasterScatterPlugin

    return RasterScatterPlugin(iface)