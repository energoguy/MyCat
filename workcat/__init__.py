"""MyCat - a pixel cat that sits on the window you work in and learns your routine."""

APP_NAME = "MyCat"  # what people see: windows, shortcuts, the setup file
# Up to 0.6 the app was called WorkCat. Two things keep that name on purpose:
OLD_NAME = "WorkCat"  # under it an earlier version left its folders and its "start with Windows" entry: they are taken over
INSTANCE = "WorkCat"  # how a running cat is known to a second start and to the setup program. Nobody sees it, and an update finds a running older cat by it
__version__ = "0.10.0"
