"""
An attempt at a user friendly Cart3d GUI
"""
# -*- coding: utf-8 -*-
from __future__ import division, unicode_literals, print_function
from six import string_types, iteritems
from six.moves import range

# standard library
import sys
import os.path
import cgi #  html lib
import datetime
import traceback

# 3rd party
from numpy import ndarray, eye
import vtk
from vtk.qt4.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PyQt4 import QtCore, QtGui

# pyNastran
import pyNastran
from pyNastran.utils import print_bad_path
from pyNastran.utils.log import SimpleLogger
from pyNastran.gui.formats import Cart3dIO, is_cart3d
from pyNastran.gui.arg_handling import get_inputs
from pyNastran.gui.qt_files.qt_legend import LegendPropertiesWindow
from pyNastran.gui.qt_files.gui_qt_common import GuiCommon

import signal
signal.signal(signal.SIGINT, signal.SIG_DFL)

if not is_cart3d:
    raise ImportError()

try:
    pkg_path = sys._MEIPASS #@UndefinedVariable
    script_path = os.path.join(pkg_path, 'scripts')
    icon_path = os.path.join(pkg_path, 'icons')
except:
    pkg_path = pyNastran.__path__[0]
    script_path = os.path.join(pkg_path, 'gui', 'scripts')
    icon_path = os.path.join(pkg_path, 'gui', 'icons')


#from pyNastran.gui.formats import NastranIO

class MainWindow(QtGui.QMainWindow, GuiCommon, Cart3dIO):
    def __init__(self, inputs):
        QtGui.QMainWindow.__init__(self)
        GuiCommon.__init__(self)
        Cart3dIO.__init__(self)
        #NastranIO.__init__(self)

        settings = QtCore.QSettings()
        self.supported_formats = []
        self._setup_supported_formats()

        self.Title = None
        self.min_value = None
        self.max_value = None
        self.blue_to_red = False
        self._is_axes_shown = True
        self.nvalues = 9
        self.is_wireframe = False
        self.modelType = None

        #-------------
        # inputs dict
        self.is_edges = inputs['is_edges']
        self.is_nodal = inputs['is_nodal']
        self.is_centroidal = inputs['is_centroidal']
        self.magnify = inputs['magnify']
        assert self.is_centroidal != self.is_nodal, "is_centroidal and is_nodal can't be the same and are set to \"%s\"" % self.is_nodal
        #format = inputs['format']  # the active format loaded into the gui
        format = 'cart3d'
        input = inputs['input']
        output = inputs['output']
        script = inputs['script']

        debug = inputs['debug']
        self.debug = debug
        assert debug in [True, False], 'debug=%s' % debug
        shots = inputs['shots']
        if shots is None:
            shots = []

        #-------------
        # file
        self.format = None
        self.infile_name = None
        self.out_filename = None
        self.dirname = ''
        self.last_dir = '' # last visited directory while opening file

        #-------------
        # internal params
        self.show_info = True
        self.show_debug = True
        self.show_gui = True
        self.show_command = True
        self.coord_id = 0

        self.nCases = 0
        self.iCase = 0
        self.nNodes = 0
        self.nElements = 0

        #-------------
        # logging

        self.log = SimpleLogger('debug', lambda x, y: self.logg_msg(x, y))
        # logging needs synchronizing, so the messages from different threads
        # would not be interleave
        self.log_mutex = QtCore.QReadWriteLock()

        #-------------
        self.create_vtk_actors()

        # build GUI and restore saved application state
        self.restoreGeometry(settings.value("mainWindowGeometry").toByteArray())
        self.background_col = settings.value("backgroundColor", (0.1, 0.2, 0.4)).toPyObject()

        self.init_ui()
        self.init_cell_picker()

        self.restoreState(settings.value("mainWindowState").toByteArray())

        #-------------
        # loading
        self.show()

        self.load_batch_inputs(inputs)

        if shots:
            self.on_take_screenshot(shots)
            sys.exit('took screenshot %r' % shots)

        if script:
            self.on_run_script(script)

    def _setup_supported_formats(self):
        self.formats = {
            'cart3d' : is_cart3d,
        }
        for (name, is_on) in sorted(iteritems(self.formats)):
            if is_on:
                self.supported_formats.append(name)

    def load_batch_inputs(self, inputs):
        if not inputs['format']:
            return
        form = inputs['format'].lower()
        input = inputs['input']
        output = inputs['output']
        is_failed = self.on_load_geometry(input, form)
        if is_failed:
            return
        if output:
            self.on_load_results(output)
        self._simulate_key_press('r')
        self.vtk_interactor.Modified()

    def create_cell_picker(self):
        # cell picker
        self.cell_picker = vtk.vtkCellPicker()

    def init_cell_picker(self):
        self.is_pick = False
        self.vtk_interactor.SetPicker(self.cell_picker)
        #self.vtk_interactor.SetPicker(self.point_picker)

        def annotate_cell_picker(object, event):
            self.log_command("annotate_cell_picker()")
            picker = self.cell_picker
            if picker.GetCellId() < 0:
                #self.picker_textActor.VisibilityOff()
                pass
            else:
                worldPosition = picker.GetPickPosition()
                cell_id = picker.GetCellId()
                #ds = picker.GetDataSet()
                selPt = picker.GetSelectionPoint()
                self.log_command("annotate_picker()")
                self.log_info("worldPosition = %s" % str(worldPosition))
                self.log_info("cell_id = %s" % cell_id)
                #self.log_info("data_set = %s" % ds)
                self.log_info("selPt = %s" % str(selPt))

                #self.picker_textMapper.SetInput("(%.6f, %.6f, %.6f)"% pickPos)
                #self.picker_textActor.SetPosition(selPt[:2])
                #self.picker_textActor.VisibilityOn()

        self.cell_picker.AddObserver("EndPickEvent", annotate_cell_picker)

    def logg_msg(self, typ, msg):
        """
        Add message to log widget trying to choose right color for it.
        @param msg message to be displayed
        """
        _fr =  sys._getframe(4)  # jump to get out of the logger code
        n = _fr.f_lineno
        fn = os.path.basename(_fr.f_globals['__file__'])

        if typ == 'DEBUG' and not self.show_debug:
            return
        elif typ == 'INFO' and not self.show_info:
            return
        elif typ == 'GUI' and not self.show_gui:
            return
        elif typ == 'COMMAND' and not self.show_command:
            return

        msg = '   fname=%-25s lineNo=%-4s   %s\n' % (fn, n, msg)

        tim = datetime.datetime.now().strftime('[%d-%m-%Y %H:%M:%S]')
        msg = cgi.escape(msg)
        #message colors
        dark_orange = '#EB9100'
        cols = {"GUI": "blue", "COMMAND":"green", "GUI ERROR":"Crimson", "DEBUG" : dark_orange}
        msg = msg.rstrip().replace('\n', '<br>')
        msg = tim + ' ' + (typ + ': ' + msg) if typ else msg
        if typ in cols:
            msg = '<font color="%s"> %s </font>' % (cols[typ], msg)

        self.log_mutex.lockForWrite()
        text_cursor = self.log_widget.textCursor()
        end = text_cursor.End
        #print("end", end)
        text_cursor.movePosition(end)
        #print(dir(text_cursor))
        text_cursor.insertHtml(msg + r"<br />")
        self.log_widget.ensureCursorVisible() # new message will be visible
        self.log_mutex.unlock()

    def log_info(self, msg):
        """ Helper funtion: log a messaage msg with a 'GUI:' prefix """
        self.log.simple_msg(msg, 'GUI')

    def log_command(self, msg):
        """ Helper funtion: log a messaage msg with a 'GUI:' prefix """
        self.log.simple_msg(msg, 'COMMAND')

    def log_error(self, msg):
        """ Helper funtion: log a messaage msg with a 'GUI:' prefix """
        self.log.simple_msg(msg, 'GUI ERROR')

    def change_background_col(self):
        """ Choose a background color """
        c =  [int(255 * i) for i in self.background_col]
        col = QtGui.QColorDialog.getColor(QtGui.QColor(*c), self, "Choose a background color")
        if col.isValid():
            self.background_col = col.getRgbF()[:3]
            self.rend.SetBackground(*self.background_col)

    def about_dialog(self):
        """ Display about dialog """
        #if fmode == 1:  # PyQt
        copyright = pyNastran.__pyqt_copyright__
        #else:
            #copyright = pyNastran.__copyright__

        about = [
            'pyCart3d QT GUI',
            '',
            'pyCart3d v%s' % pyNastran.__version__,
            copyright,
            pyNastran.__author__,
            '',
            '%s' % pyNastran.__website__,
            '',
            'Mouse',
            'Left Click - Rotate',
            'Middle Click - Pan/Recenter Rotation Point',
            'Shift + Left Click - Pan/Recenter Rotation Point',
            'Right Mouse / Wheel - Zoom',
            '',
            'Keyboard Controls',
            #'r   - reset camera view',
            #'X/x - snap to x axis',
            #'Y/y - snap to y axis',
            #'Z/z - snap to z axis',
            #'',
            #'h   - show/hide legend & info',
            'CTRL+I - take a screenshot (image)',
            'CTRL+L - cycle results',
            #'m/M    - scale up/scale down by 1.1 times',
            #'o/O    - rotate counter-clockwise/clockwise 5 degrees',
            's      - view model as a surface',
            'w      - view model as a wireframe',
            '',
            'Reload Model:  using the same filename reload the model',
        ]
        QtGui.QMessageBox.about(self, "About pyCart3d GUI", "\n".join(about))

    def set_window_title(self, msg):
        msg2 = "pyCart3d v%s - "  % pyNastran.__version__
        msg2 += msg
        self.setWindowTitle(msg)

    def _build_menubar(self):
        ## menubar
        self.menubar = self.menuBar()
        self.menu_file = self.menubar.addMenu('&File')
        self.menu_view = self.menubar.addMenu('&View')
        self.menu_window = self.menubar.addMenu('&Window')
        self.menu_help = self.menubar.addMenu('&Help')

        ## toolbar
        self.toolbar = self.addToolBar('Show toolbar')
        self.toolbar.setObjectName('main_toolbar')

        # prepare actions that will  be used in application
        actions = {}
        pth = os.path.join(icon_path, 'tbdf.png')

        checkables = ['show_info', 'show_debug', 'show_gui', 'show_command']
        if os.path.exists(script_path):
            scripts = [script for script in os.listdir(script_path) if '.py' in script ]
        else:
            scripts = []

        scripts = tuple(scripts)

        tools = [
          ('exit', '&Exit', os.path.join(icon_path, 'texit.png'), 'Ctrl+Q', 'Exit application', QtGui.qApp.quit),
          ('load_geometry', 'Load &Geometry', os.path.join(icon_path, 'load_geometry.png'), 'Ctrl+O', 'Loads a geometry input file', self.on_load_geometry),  ## @todo no picture...
          ('load_results', 'Load &Results',   os.path.join(icon_path, 'load_results.png'), 'Ctrl+R', 'Loads a results file', self.on_load_results),  ## @todo no picture...
          ('back_col', 'Change background color', os.path.join(icon_path, 'tcolorpick.png'), None, 'Choose a background color', self.change_background_col),
          ('legend', 'Modify legend', os.path.join(icon_path, 'legend.png'), None, 'Set Legend', self.set_legend),
          ('axis', 'Show/Hide Axis', os.path.join(icon_path, 'axis.png'), None, 'Show/Hide Global Axis', self.on_show_hide_axes),

          ('wireframe', 'Wireframe Model', os.path.join(icon_path, 'twireframe.png'), 'w', 'Show Model as a Wireframe Model', self.on_wireframe),
          ('surface', 'Surface Model', os.path.join(icon_path, 'tsolid.png'), 's', 'Show Model as a Surface Model', self.on_surface),
          ('edges', 'Show/Hide Edges', os.path.join(icon_path, 'tedges.png'), 'e', 'Show/Hide Model Edges', self.on_flip_edges),

          ('show_info', 'Show INFO', os.path.join(icon_path, 'show_info.png'), None, 'Show "INFO" messages', self.on_show_info),
          ('show_debug', 'Show DEBUG', os.path.join(icon_path, 'show_debug.png'), None, 'Show "DEBUG" messages', self.on_show_debug),
          ('show_gui', 'Show GUI', os.path.join(icon_path, 'show_gui.png'), None, 'Show "GUI" messages', self.on_show_gui),
          ('show_command', 'Show COMMAND', os.path.join(icon_path, 'show_command.png'), None, 'Show "COMMAND" messages', self.on_show_command),

          ('magnify', 'Magnify', os.path.join(icon_path, 'plus_zoom.png'), 'M', 'Increase Magnfication', self.on_increase_magnification),
          ('shrink', 'Shrink', os.path.join(icon_path, 'minus_zoom.png'), 'm', 'Decrease Magnfication', self.on_decrease_magnification),

          #('cell_pick', 'Cell Pick', '', 'CTRL+K', 'PickTip', self.on_cell_picker),

          ('rotate_clockwise', 'Rotate Clockwise', os.path.join(icon_path, 'tclock.png'), 'o', 'Rotate Clockwise', self.on_rotate_clockwise),
          ('rotate_cclockwise', 'Rotate Counter-Clockwise', os.path.join(icon_path, 'tcclock.png'), 'O', 'Rotate Counter-Clockwise', self.on_rotate_cclockwise),

          ('scshot', 'Take a Screenshot', os.path.join(icon_path, 'tcamera.png'), 'CTRL+I', 'Take a Screenshot of current view', self.take_screenshot),
          ('about', 'About pyCart3d GUI', os.path.join(icon_path, 'tabout.png'), 'CTRL+H', 'About pyCart3d GUI and help on shortcuts', self.about_dialog),
          ('creset', 'Reset camera view', os.path.join(icon_path, 'trefresh.png'), 'r', 'Reset the camera view to default', self.on_reset_camera),
          ('reload', 'Reload model', os.path.join(icon_path, 'treload.png'), 'r', 'Reload the model', self.on_reload),

          ('cycle_res', 'Cycle Results', os.path.join(icon_path, 'cycle_results.png'), 'CTRL+L', 'Changes the result case', self.cycleResults),

          ('x', 'Flips to +X Axis', os.path.join(icon_path, 'plus_x.png'), 'x', 'Flips to +X Axis', lambda: self.update_camera('+x')),
          ('y', 'Flips to +Y Axis', os.path.join(icon_path, 'plus_y.png'), 'y', 'Flips to +Y Axis', lambda: self.update_camera('+y')),
          ('z', 'Flips to +Z Axis', os.path.join(icon_path, 'plus_z.png'), 'z', 'Flips to +Z Axis', lambda: self.update_camera('+z')),

          ('X', 'Flips to -X Axis', os.path.join(icon_path, 'minus_x.png'), 'X', 'Flips to -X Axis', lambda: self.update_camera('-x')),
          ('Y', 'Flips to -Y Axis', os.path.join(icon_path, 'minus_y.png'), 'Y', 'Flips to -Y Axis', lambda: self.update_camera('-y')),
          ('Z', 'Flips to -Z Axis', os.path.join(icon_path, 'minus_z.png'), 'Z', 'Flips to -Z Axis', lambda: self.update_camera('-z')),
          ('script', 'Run Python script', os.path.join(icon_path, 'python48.png'), None, 'Runs pyCart3dGUI in batch mode', self.on_run_script),
        ]

        if 0:
            print('script_path =', script_path)
            print('scripts =', scripts)
            self.menu_scripts = self.menubar.addMenu('&Scripts')
            for script in scripts:
                fname = os.path.join(script_path, script)
                tool = (script, script, os.path.join(icon_path, 'python48.png'), None, '', lambda: self.on_run_script(fname) )
                tools.append(tool)
        else:
            self.menu_scripts = None

        for (nam, txt, icon, shortcut, tip, func) in tools:
            if icon is None:
                print("missing_icon = %r!!!" % nam)
            else:
                ico = QtGui.QIcon()
                ico.addPixmap(QtGui.QPixmap(icon), QtGui.QIcon.Normal, QtGui.QIcon.Off)

            if nam in checkables:
                actions[nam] = QtGui.QAction(ico, txt, self, checkable=True)
                actions[nam].setChecked(True)
            else:
                actions[nam] = QtGui.QAction(ico, txt, self)

            if shortcut:
                actions[nam].setShortcut(shortcut)
            if tip:
                actions[nam].setStatusTip(tip)
            if func:
                actions[nam].triggered.connect(func)

        actions['toolbar'] = self.toolbar.toggleViewAction()
        actions['toolbar'].setStatusTip("Show/Hide application toolbar")

        actions['reswidget'] = self.res_dock.toggleViewAction()
        actions['reswidget'].setStatusTip("Show/Hide results selection")

        actions['logwidget'] = self.log_dock.toggleViewAction()
        actions['logwidget'].setStatusTip("Show/Hide application log")

        menu_items = [(self.menu_file, ('load_geometry', 'load_results', 'script', '', 'exit')),
                      (self.menu_view,  ('scshot', '', 'wireframe', 'surface', 'creset', '', 'back_col', 'legend','axis', '', 'show_info', 'show_debug', 'show_gui', 'show_command')),
                      (self.menu_window,('toolbar', 'reswidget', 'logwidget' )),
                      (self.menu_help,  ('about',)),
                      (self.menu_scripts, scripts),
                      (self.toolbar, ('reload', 'load_geometry', 'load_results', 'cycle_res',
                                      'x', 'y', 'z', 'X', 'Y', 'Z',
                                      'magnify', 'shrink', 'rotate_clockwise', 'rotate_cclockwise',
                                      'wireframe', 'surface', 'edges', 'creset', 'scshot', '', 'exit'))]
        # populate menus and toolbar
        for menu, items in menu_items:
            if menu is None:
                continue
            for i in items:
                if not i:
                    menu.addSeparator()
                else:
                    menu.addAction(actions[i] if isinstance(i, string_types) else i())

    def init_ui(self):
        """ Initialize user iterface"""
        self.resize(800, 600)
        self.statusBar().showMessage('Ready')

        # windows title and aplication icon
        self.setWindowTitle('Statusbar')
        self.setWindowIcon(QtGui.QIcon(os.path.join(icon_path, 'logo.png')))
        self.set_window_title("pyCart3d v%s"  % pyNastran.__version__)

        #=========== Results widget ===================
        self.res_dock = QtGui.QDockWidget("Results", self)
        self.res_dock.setObjectName("results_obj")
        self.res_widget = QtGui.QTextEdit()
        self.res_widget.setReadOnly(True)
        self.res_dock.setWidget(self.res_widget)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.res_dock)
        #=========== Logging widget ===================
        self.log_dock = QtGui.QDockWidget("Application log", self)
        self.log_dock.setObjectName("application_log")
        self.log_widget = QtGui.QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_dock.setWidget(self.log_widget)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.log_dock)
        #===============================================

        self._build_menubar()

        # right sidebar
        self.res_dock.hide()

        self.build_vtk_frame()

    def create_vtk_actors(self):
        # vtk actors
        self.grid = vtk.vtkUnstructuredGrid()
        self.grid2 = vtk.vtkUnstructuredGrid()

        # edges
        self.edgeActor = vtk.vtkActor()
        self.edgeMapper = vtk.vtkPolyDataMapper()

        self.create_cell_picker()

        # scalar bar
        self.scalarBar = vtk.vtkScalarBarActor()
        self.create_global_axes()

    def create_coordinate_system(self, label='', origin=None, matrix_3x3=None, Type='xyz', add_to_ren=True):
        """
        Creates a coordinate system

        :param origin:
          the origin as (3,) ndarray/list/tuple
        :param matrix_3x3:
          a standard 3x3 Nastran-style coordinate system
        :param Type:
          a string of 'xyz', 'Rtz', 'Rtp' (xyz, cylindrical, spherical)
          that changes the axis names

        ..todo::
          Type is not supported ('xyz' ONLY)
        ..todo::
          Can only set one coordinate system
        ..seealso::
          http://en.wikipedia.org/wiki/Homogeneous_coordinates
          http://www3.cs.stonybrook.edu/~qin/courses/graphics/camera-coordinate-system.pdf
          http://www.vtk.org/doc/nightly/html/classvtkTransform.html#ad58b847446d791391e32441b98eff151
        """
        coord_id = self.coord_id

        transform = vtk.vtkTransform()
        if origin is None and matrix_3x3 is None:
            pass
        elif origin is not None and matrix_3x3 is None:
            print('origin%s = %s' % (label, str(origin)))
            transform.Translate(*origin)
        elif matrix_3x3 is not None:  # origin can be None
            m = eye(4, dtype='float32')
            m[:3, :3] = matrix_3x3
            if origin is not None:
                m[:3, 3] = origin
            transform.SetMatrix(m.ravel())
        else:
            raise RuntimeError('unexpected coordinate system')

        axes = vtk.vtkAxesActor()
        axes.SetUserTransform(transform)

        if Type != 'xyz':
            if Type == 'Rtz':
                x = 'R'
                y = 't'
                z = 'z'

                x = 'R'
                y = 'theta'
                z = 'z'

            elif Type == 'Rtp':
                x = 'R'
                #y = 't'
                #z = 'p'

                #x = 'R'
                y = 'theta'
                z = 'phi'
            else:
                raise RuntimeError('invalid axis type; Type=%r' % Type)

            x = '%s%s' % (x, label)
            y = '%s%s' % (y, label)
            z = '%s%s' % (z, label)
            axes.SetXAxisLabelText(x)
            axes.SetYAxisLabelText(y)
            axes.SetZAxisLabelText(z)
        else:
            if label:
                x = 'x%s' % label
                y = 'y%s' % label
                z = 'z%s' % label
                axes.SetXAxisLabelText(x)
                axes.SetYAxisLabelText(y)
                axes.SetZAxisLabelText(z)

        self.transform[coord_id] = transform
        self.axes[coord_id] = axes
        self.coord_id += 1
        if add_to_ren:
            self.rend.AddActor(axes)
        return self.coord_id

    def create_global_axes(self):
        self.transform = {}
        self.axes = {}
        self.create_coordinate_system(label='', origin=None, matrix_3x3=None, Type='xyz', add_to_ren=False)

    def on_show_hide_axes(self):
        # this method should handle all the coords when
        # there are more then one
        if self._is_axes_shown:
            for key, axis in iteritems(self.axes):
                axis.VisibilityOff()
        else:
            for key, axis in iteritems(self.axes):
                axis.VisibilityOn()
        self._is_axes_shown = not(self._is_axes_shown)

    def build_vtk_frame(self):
        #Frame that VTK will render on
        vtk_frame = QtGui.QFrame()
        vtk_hbox  = QtGui.QHBoxLayout()
        vtk_hbox.setContentsMargins(2, 2, 2, 2)

        #Qt VTK RenderWindowInteractor
        self.vtk_interactor = QVTKRenderWindowInteractor(parent=vtk_frame)
        self.iren = self.vtk_interactor
        vtk_hbox.addWidget(self.vtk_interactor)
        vtk_frame.setLayout(vtk_hbox)
        vtk_frame.setFrameStyle(QtGui.QFrame.NoFrame | QtGui.QFrame.Plain)
        # this is our main, 'central' widget
        self.setCentralWidget(vtk_frame)

        #=============================================================
        self.rend = vtk.vtkRenderer()
        self.vtk_interactor.GetRenderWindow().AddRenderer(self.rend)
        self.vtk_interactor.GetRenderWindow().Render()
        self.textActors = {}

        for cid, axes in self.axes.iteritems():
            self.rend.AddActor(axes)
        self.addGeometry()
        self.addAltGeometry()
        self.rend.GetActiveCamera().ParallelProjectionOn()
        self.rend.SetBackground(*self.background_col)
        self.rend.ResetCamera()
        self._simulate_key_press('t') # change mouse style to trackball
        self.build_lookup_table()

        self.magnify = 1
        self.iText = 0
        textSize = 14 * self.magnify
        self.createText([5, 50], 'Max  ', textSize)  # text actor 0
        self.createText([5, 35], 'Min  ', textSize)  # text actor 1
        self.createText([5, 20], 'Word1', textSize)  # text actor 2
        self.createText([5, 5], 'Word2', textSize)  # text actor 3

        self.get_edges()
        if self.is_edges:
            prop = self.edgeActor.GetProperty()
            prop.EdgeVisibilityOn()
        else:
            prop = self.edgeActor.GetProperty()
            prop.EdgeVisibilityOff()

    def set_legend(self):
        """
        Opens a dialog box to set:

        +--------+----------+
        |  Name  |  String  |
        +--------+----------+
        |  Min   |  Float   |
        +--------+----------+
        |  Max   |  Float   |
        +--------+----------+
        | Format | pyString |
        +--------+----------+
        """
        if not hasattr(self, 'caseKeys'):
            self.log_error('No model has been loaded.')
            return
        key = self.caseKeys[self.iCase]
        case = self.resultCases[key]
        #print("len(case) = %i" % len(case))
        (subcaseID, resultType, vectorSize, location, data_format) = key

        data = {
            'name' : resultType,
            'min' : case.min(),
            'max' : case.max(),
            'format' : data_format,
            'is_blue_to_red' : True,
            'is_discrete': True,
            'clicked_ok' : False,
        }
        legend = LegendPropertiesWindow(data, win_parent=self)
        legend.show()
        legend.exec_()

        if data['clicked_ok']:
            Title = data['name']
            min_value = data['min']
            max_value = data['max']
            data_format = data['format']
            is_blue_to_red = data['is_blue_to_red']
            is_discrete = data['is_discrete']
            self.on_update_legend(Title=Title, min_value=min_value, max_value=max_value,
                                  data_format=data_format,
                                  is_blue_to_red=is_blue_to_red,
                                  is_discrete=is_discrete)

    def on_update_legend(self, Title='Title', min_value=0., max_value=1.,
                      data_format='%.0f', is_blue_to_red=True, is_discrete=True):
        key = self.caseKeys[self.iCase]
        case = self.resultCases[key]
        #print("len(case) = %i" % len(case))
        (subcase_id, _resultType, vectorSize, location, _data_format) = key

        try:
            caseName = self.iSubcaseNameMap[subcase_id]
        except KeyError:
            caseName = ('case=NA', 'label=NA')
        (subtitle, label) = caseName

        gridResult = self.build_grid_result(vectorSize, location)
        norm_value, nValueSet = self.set_grid_values(gridResult, case, vectorSize, min_value, max_value, is_blue_to_red=is_blue_to_red)
        self.UpdateScalarBar(Title, min_value, max_value, norm_value, data_format, is_blue_to_red=is_blue_to_red)
        self.final_grid_update(gridResult, key, subtitle, label)
        self.log_command('self.on_update_legend(Title=%r, min_value=%s, max_value=%s,\n'
                         '                      data_format=%r, is_blue_to_red=%s, is_discrete=%s)'
                         % (Title, min_value, max_value, data_format, is_blue_to_red, is_discrete))

    def on_run_script(self, python_file=False):
        print('python_file =', python_file)
        if python_file in [None, False]:
            Title = 'Choose a Python Script to Run'
            wildcard = "Python (*.py)"
            wildcard_index, infile_name = self._create_load_file_dialog(wildcard, Title)
            if not infile_name:
                is_failed = True
                return is_failed # user clicked cancel

            python_file = os.path.join(script_path, infile_name)
        execfile(python_file)
        self.log_command('self.on_run_script(%r)' % python_file)

    def on_show_info(self):
        self.show_info = not(self.show_info)

    def on_show_debug(self):
        self.show_debug = not(self.show_debug)

    def on_show_gui(self):
        self.show_gui = not(self.show_gui)

    def on_show_command(self):
        self.show_command = not(self.show_command)

    def on_reset_camera(self):
        self.log_command('on_reset_camera()')
        self._simulate_key_press('r')

    def on_surface(self):
        if self.is_wireframe:
            self.log_command('on_surface()')
            self._simulate_key_press('s')
            self.is_wireframe = False

    def on_wireframe(self):
        if not self.is_wireframe:
            self.log_command('on_wireframe()')
            self._simulate_key_press('w')
            self.is_wireframe = True

    def _update_camera(self, camera=None):
        if camera is None:
            camera = self.GetCamera()
        camera.Modified()
        self.vtk_interactor.Render()

    def zoom(self, value):
        camera = self.GetCamera()
        camera.Zoom(value)
        camera.Modified()
        self.vtk_interactor.Render()
        self.log_command('zoom(%s)' % value)

    def rotate(self, rotate_deg):
        camera = self.GetCamera()
        camera.Roll(-rotate_deg)
        camera.Modified()
        self.vtk_interactor.Render()
        self.log_command('rotate(%s)' % rotate_deg)

    def on_rotate_clockwise(self):
        self.rotate(15.0)

    def on_rotate_cclockwise(self):
        self.rotate(-15.0)

    def on_increase_magnification(self):
        self.zoom(1.1)

    def on_decrease_magnification(self):
        self.zoom(1.0/1.1)

    def on_flip_edges(self):
        self.is_edges = not(self.is_edges)
        self.edgeActor.SetVisibility(self.is_edges)
        self.edgeActor.Modified()
        self._update_camera()
        self.log_command('on_flip_edges()')

    def get_edges(self):
        """
        ..todo:: For some reason, the edge color is set to the parent
        surface's color instead of black
        """
        edges = vtk.vtkExtractEdges()
        edges.SetInput(self.grid)
        self.edgeMapper.SetInput(edges.GetOutput())

        self.edgeActor.SetMapper(self.edgeMapper)
        self.edgeActor.GetProperty().SetColor(0, 0, 0)

        prop = self.edgeActor.GetProperty()
        prop.SetColor(0, 0, 0)
        self.edgeActor.SetVisibility(self.is_edges)
        self.rend.AddActor(self.edgeActor)

    def createText(self, position, label, textSize=18, movable=False):
        txt = vtk.vtkTextActor()
        txt.SetInput(label)
        txtprop = txt.GetTextProperty()
        txtprop.SetFontSize(textSize)
        txtprop.SetColor(1, 1, 1)
        txt.SetDisplayPosition(*position)

        txt.VisibilityOff()

        # assign actor to the renderer
        self.rend.AddActor(txt)
        self.textActors[self.iText] = txt
        self.iText += 1

    def TurnTextOff(self):
        for (i, text) in iteritems(self.textActors):
            text.VisibilityOff()

    def TurnTextOn(self):
        for (i, text) in iteritems(self.textActors):
            text.VisibilityOn()

    def build_lookup_table(self):
        """TODO: add support for NanColors"""
        self.colorFunction = vtk.vtkColorTransferFunction()
        self.colorFunction.SetColorSpaceToHSV()
        self.colorFunction.HSVWrapOff()

        drange = [10., 20.]
        # blue - low
        # red - high
        self.colorFunction.AddRGBPoint(drange[0], 0.0, 0.0, 1.0)
        self.colorFunction.AddRGBPoint(drange[1], 1.0, 0.0, 0.0)

        self.scalarBar.SetTitle("Title1")
        self.scalarBar.SetLookupTable(self.colorFunction)
        self.scalarBar.SetOrientationToVertical()

        self.scalarBar.SetHeight(0.9)
        self.scalarBar.SetWidth(0.20)  # the width is set first
        # after the width is set, this is adjusted
        self.scalarBar.SetPosition(0.77, 0.1)

        propTitle = vtk.vtkTextProperty()
        propTitle.SetFontFamilyToArial()
        propTitle.BoldOn()
        propTitle.ShadowOn()

        propLabel = vtk.vtkTextProperty()
        propLabel.BoldOff()
        propLabel.ShadowOn()

        scalar_range = self.grid.GetScalarRange()
        self.aQuadMapper.SetScalarRange(scalar_range)
        self.aQuadMapper.SetLookupTable(self.colorFunction)

        self.scalarBar.SetLabelFormat("%i")

        # allows 0-1 to be nice number when ranging values (gotta pick something)
        self.scalarBar.SetNumberOfLabels(11)
        self.scalarBar.SetMaximumNumberOfColors(11)

        self.rend.AddActor(self.scalarBar)
        self.scalarBar.VisibilityOff()

    def on_reload(self):
        Title = self.Title
        if self.format == 'usm3d':
            self.step_results_usm3d()
        else:
            self.on_load_geometry(self.infile_name, self.format)

        msg = '%s - %s - %s' % (self.format, self.infile_name, self.out_filename)
        self.set_window_title(msg)
        self.log_command('on_reload()')
        #self.cycleResults(Title)
        for i in range(10):  #  limit on number of cycles
            if self.Title != Title:
                self.cycleResults(Title)
            else:
                break

    def on_load_geometry(self, infile_name=None, geometry_format=None):
        wildcard = ''
        is_failed = False

        if geometry_format and geometry_format.lower() not in self.supported_formats:
            is_failed = True
            if geometry_format in self.formats:
                msg = 'The import for the %r module failed.\n' % geometry_format
            else:
                msg = '%r is not a enabled format; enabled_formats=%s\n' % (geometry_format, self.supported_formats)
                msg += str("formats = %s" % str(self.formats))
            self.log_error(msg)
            return is_failed

        if infile_name:
            geometry_format = geometry_format.lower()
            print("geometry_format = %r" % geometry_format)
            if geometry_format == 'cart3d' and is_cart3d:
                has_results = True
                load_function = self.load_cart3d_geometry
            else:
                self.log_error('---invalid format=%r' % geometry_format)
                is_failed = True
                return is_failed
                raise NotImplementedError('on_load_geometry; infile_name=%r format=%r' % (infile_name, geometry_format))
            formats = [geometry_format]
            filter_index = 0
        else:
            formats = []
            load_functions = []
            has_results_list = []
            wildcard_list = []
            if is_cart3d:
                wildcard_list.append("Cart3d (*.tri; *.triq)")
                formats.append('Cart3d')
                has_results_list.append(True)
                load_functions.append(self.load_cart3d_geometry)

            wildcard = ';;'.join(wildcard_list)

            # get the filter index and filename
            if infile_name is not None and geometry_format is not None:
                filter_index = formats.index(geometry_format)
            else:
                Title = 'Choose a Geometry File to Load'
                wildcard_index, infile_name = self._create_load_file_dialog(wildcard, Title)
                if not infile_name:
                    is_failed = True
                    return is_failed # user clicked cancel
                filter_index = wildcard_list.index(wildcard_index)

            geometry_format = formats[filter_index]
            load_function = load_functions[filter_index]
            has_results = has_results_list[filter_index]

        if load_function is not None:
            self.last_dir = os.path.split(infile_name)[0]

            self.grid.Reset()
            self.grid.Modified()
            self.grid2.Reset()
            self.grid2.Modified()

            if not os.path.exists(infile_name) and geometry_format:
                msg = 'input file=%r does not exist' % infile_name
                self.log_error(msg)
                self.log_error(print_bad_path(infile_name))
                return

            if self.modelType is not None:
                # clear out old data
                name = 'clear_' + self.modelType

                # call the clear method
                try:
                    dy_method = getattr(self, 'clear_' + self.modelType)
                    dy_method()
                except:
                    print("method %r does not exist" % name)
            self.log_info("reading %s file %r" % (geometry_format, infile_name))
            try:
                has_results = load_function(infile_name, self.last_dir)
            except Exception as e:
                msg = traceback.format_exc()
                self.log_error(msg)
                raise
            self.rend.ResetCamera()

        # the model has been loaded, so we enable load_results
        if filter_index >= 0:
            self.format = formats[filter_index].lower()
            if has_results:
                enable = True
            else:
                enable = False
        else: # no file specified
            return
        self.infile_name = infile_name

        if self.out_filename is not None:
            msg = '%s - %s - %s' % (self.format, self.infile_name, self.out_filename)
        else:
            msg = '%s - %s' % (self.format, self.infile_name)
        self.set_window_title(msg)
        self.log_command("on_load_geometry(infile_name=%r, geometry_format=%r)" % (infile_name, self.format))

    def _create_load_file_dialog(self, qt_wildcard, Title):
        # getOpenFileName return QString and we want Python string
        fname, wildcard_level = QtGui.QFileDialog.getOpenFileNameAndFilter(self, Title, self.last_dir, qt_wildcard)
        return str(wildcard_level), str(fname)

    def on_load_results(self, out_filename=None):
            geometry_format = self.format
            if self.format is None:
                msg ='on_load_results failed:  You need to load a file first...'
                self.log_error(msg)
                raise RuntimeError(msg)

            if out_filename in [None, False]:
                Title = 'Select a Results File for %s' % self.format
                wildcard = None
                if geometry_format == 'cart3d':
                    has_results = True
                    wildcard = "Cart3d (*.triq)"
                    load_functions = [self.load_cart3d_results]
                else:
                    msg = 'format=%r is not supported' % geometry_format
                    self.log_error(msg)
                    raise RuntimeError(msg)

                load_function = load_functions[0]
                if wildcard is None:
                    msg = 'format=%r has no method to load results' % geometry_format
                    self.log_error(msg)
                    return
                wildcard_index, out_filename = self._create_load_file_dialog(wildcard, Title)
            else:
                if geometry_format == 'cart3d':
                    load_function = self.load_cart3d_results
                else:
                    msg = 'format=%r is not supported.  Did you load a geometry model?' % geometry_format
                    self.log_error(msg)
                    raise RuntimeError(msg)

            if out_filename == '':
                return
            if not os.path.exists(out_filename):
                msg = 'result file=%r does not exist' % out_filename
                self.log_error(msg)
                return
            self.last_dir = os.path.split(out_filename)[0]
            load_function(out_filename, self.last_dir)

            self.out_filename = out_filename
            msg = '%s - %s - %s' % (self.format, self.infile_name, out_filename)
            self.set_window_title(msg)
            print("on_load_results(%r)" % out_filename)
            self.out_filename = out_filename
            self.log_command("on_load_results(%r)" % out_filename)

    def take_screenshot(self):
        """ Take a screenshot of a current view and save as a file"""
        self.on_take_screenshot(None)

    def on_take_screenshot(self, fname):
        """ Take a screenshot of a current view and save as a file"""
        if fname is None:
            filt = QtCore.QString()
            default_filename = ''

            Title = ''
            if self.Title is not None:
                Title = self.Title

            if self.out_filename is None:
                default_filename = ''
                if self.infile_name is not None:
                    base, ext = os.path.splitext(os.path.basename(self.infile_name))
                    default_filename = self.infile_name
            else:
                base, ext = os.path.splitext(os.path.basename(self.out_filename))
                default_filename = Title + '_' + base

            fname = str(QtGui.QFileDialog.getSaveFileName(self, ('Choose a filename '
                        'and type'), default_filename, ('PNG Image *.png (*.png);; JPEG Image '
                        '*.jpg *.jpeg (*.jpg, *.jpeg);; TIFF Image *.tif *.tiff '
                        '(*.tif, *.tiff);; BMP Image *.bmp (*.bmp);; PostScript '
                        'Document *.ps (*.ps)'), filt))
            if fname is None or fname == '':  # 2nd option
                return
            flt = str(filt).split()[0]
        else:
            base, ext = os.path.splitext(os.path.basename(fname))
            if ext.lower() in ['png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'ps']:
                flt = ext.lower()
            else:
                flt = 'png'

        if fname:
            renderLarge = vtk.vtkRenderLargeImage()
            renderLarge.SetInput(self.rend)
            renderLarge.SetMagnification(self.magnify)

            nam, ext = os.path.splitext(fname)
            ext = ext.lower()
            for nam, exts, ob in (('PostScript', ['.ps'], vtk.vtkPostScriptWriter),
                                  ("BMP", ['.bmp'], vtk.vtkBMPWriter),
                                  ('JPG', ['.jpg', '.jpeg'], vtk.vtkJPEGWriter),
                                  ("TIFF", ['.tif', '.tiff'], vtk.vtkTIFFWriter)):
                if flt == nam:
                    fname = fname if ext in exts else fname + exts[0]
                    writer = ob()
                    break
            else:
                fname = fname if ext == '.png' else fname + '.png'
                writer = vtk.vtkPNGWriter()

            writer.SetInputConnection(renderLarge.GetOutputPort())
            writer.SetFileName(fname)
            writer.Write()
            #self.log_info("Saved screenshot: " + fname)
            self.log_command('on_take_screenshot(%r)' % fname)

    def closeEvent(self, event):
        """
        Handling saving state before application when application is being closed.
        """
        settings = QtCore.QSettings()
        settings.setValue("main_WindowGeometry", self.saveGeometry())
        settings.setValue("mainWindowState", self.saveState())
        settings.setValue("backgroundColor", self.background_col)

    def _simulate_key_press(self, key):
        """
        A little hack method that simulates pressing the key for the VTK
        interactor. There is no easy way to instruct VTK to e.g. change mouse
        style to 'trackball' (as by pressing 't' key),
        (see http://public.kitware.com/pipermail/vtkusers/2011-November/119996.html)
        therefore we trick VTK to think that a key has been pressed.

        :param key: a key that VTK should be informed about, e.g. 't'
        """
        print("key = ", key)
        if key == 'f':  # change focal point
            return
        self.vtk_interactor._Iren.SetEventInformation(0, 0, 0, 0, key, 0, None)
        self.vtk_interactor._Iren.KeyPressEvent()
        self.vtk_interactor._Iren.CharEvent()

        #if key in ['y', 'z', 'X', 'Y', 'Z']:
            #self.update_camera(key)

    def addGeometry(self):
        self.aQuadMapper = vtk.vtkDataSetMapper()
        self.aQuadMapper.SetInput(self.grid)

        geometryActor = vtk.vtkActor()
        geometryActor.SetMapper(self.aQuadMapper)
        geometryActor.GetProperty().SetDiffuseColor(1, 0, 0)  # red
        self.rend.AddActor(geometryActor)

    def addAltGeometry(self):
        self.aQuadMapper = vtk.vtkDataSetMapper()
        self.aQuadMapper.SetInput(self.grid2)
        geometryActor = vtk.vtkActor()
        geometryActor.SetMapper(self.aQuadMapper)
        geometryActor.GetProperty().SetDiffuseColor(1, 1, 0)  # green
        geometryActor.GetProperty().SetLineWidth(5)

        self.rend.AddActor(geometryActor)
        vtk.vtkPolyDataMapper().SetResolveCoincidentTopologyToPolygonOffset()

    def on_update_scalar_bar(Title, min_value, max_value, data_format):
        self.Title = str(Title)
        self.min_value = float(min_value)
        self.max_value = float(max_value)
        try:
            data_format % 1
        except:
            self.log_error("failed applying the data formatter format=%r and should be of the form: '%i', '%8f', '%.2f', '%e', etc.")
            return
        self.data_format = data_format
        self.log_command('on_update_scalar_bar(%r, %r, %r')

    def ResetCamera(self):
        self.GetCamera().ResetCamera()

    def GetCamera(self):
        return self.rend.GetActiveCamera()

    def update_camera(self, code):
        camera = self.GetCamera()
        print("code =", code)
        if code == '+x':  # set x-axis
            camera.SetFocalPoint(0., 0., 0.)
            camera.SetViewUp(0., 0., 1.)
            camera.SetPosition(1., 0., 0.)
        elif code == '-x':  # set x-axis
            camera.SetFocalPoint(0., 0., 0.)
            camera.SetViewUp(0., 0., -1.)
            camera.SetPosition(-1., 0., 0.)

        elif code == '+y':  # set y-axis
            camera.SetFocalPoint(0., 0., 0.)
            camera.SetViewUp(0., 0., 1.)
            camera.SetPosition(0., 1., 0.)
        elif code == '-y':  # set y-axis
            camera.SetFocalPoint(0., 0., 0.)
            camera.SetViewUp(0., 0., -1.)
            camera.SetPosition(0., -1., 0.)

        elif code == '+z':  # set z-axis
            camera.SetFocalPoint(0., 0., 0.)
            camera.SetViewUp(0., 1., 0.)
            camera.SetPosition(0., 0., 1.)
        elif code == '-z':  # set z-axis
            camera.SetFocalPoint(0., 0., 0.)
            camera.SetViewUp(0., -1., 0.)
            camera.SetPosition(0., 0., -1.)
        else:
            self.log_error('invalid camera code...%r' % code)
            return
        self._update_camera(camera)
        self.rend.ResetCamera()
        self.log_command('update_camera(%r)' % code)

    def finish_nastran_io(self, cases):  # same as Cart3d version
        self.resultCases = cases
        self.caseKeys = sorted(cases.keys())
        print("ncases =", len(cases))
        print("caseKeys =", self.caseKeys)

        if len(self.caseKeys) > 1:
            print("finish_io case A")
            self.iCase = -1
            self.nCases = len(self.resultCases)  # number of keys in dictionary
        elif len(self.caseKeys) == 1:
            print("finish_io case B")
            self.iCase = -1
            self.nCases = 1
        else:
            print("finish_io case C")
            self.iCase = -1
            self.nCases = 0

        self.cycleResults_explicit()  # start at nCase=0
        if self.nCases:
            self.scalarBar.VisibilityOn()
            self.scalarBar.Modified()

def main():
    app = QtGui.QApplication(sys.argv)
    QtGui.QApplication.setOrganizationName("pyCart3d")
    QtGui.QApplication.setOrganizationDomain(pyNastran.__website__)
    QtGui.QApplication.setApplicationName("pyCart3d")
    QtGui.QApplication.setApplicationVersion(pyNastran.__version__)

    inputs = get_inputs()
    window = MainWindow(inputs)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()