#!/usr/bin/python
# export PYTHONPATH=/Developer/Library/PrivateFrameworks/LLDB.framework/Resources/Python

import lldb, sys, os
from PySide import QtCore, QtGui

if len(sys.argv) <= 1:
  print "Usage: llvd <executable> [<arg> ...]"
  sys.exit(1)
executable = sys.argv[1]
arguments = sys.argv[2:]

debugger = lldb.SBDebugger.Create()
debugger.SetAsync(True)

target = debugger.CreateTargetWithFileAndArch(executable, lldb.LLDB_ARCH_DEFAULT)

app = QtGui.QApplication(sys.argv)

font = QtGui.QFont()
font.setPointSize(12)
font.setFamily("Courier")

class LineNumberArea(QtGui.QWidget):
  def __init__(self, codeWidget):
    QtGui.QWidget.__init__(self, codeWidget)
    self.__codeWidget = codeWidget

  def sizeHint(self):
    return QtCore.QSize(self.__codeWidget.lineNumberAreaWidth(), 0)

  def paintEvent(self, event):
    self.__codeWidget.lineNumberAreaPaintEvent(event)

class CodeWidget(QtGui.QPlainTextEdit):
  def __init__(self, parent=None):
    QtGui.QPlainTextEdit.__init__(self, parent)

    self.__files = {}

    self.setFont(font)

    lineNumberArea = LineNumberArea(self)
    self.__lineNumberArea = lineNumberArea

    def updateLineNumberAreaWidth(newBlockCount):
      self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)
    self.blockCountChanged.connect(updateLineNumberAreaWidth)

    def updateLineNumberArea(rect, dy):
      if dy != 0:
        lineNumberArea.scroll(0, dy)
      else:
        lineNumberArea.update(0, rect.y(), lineNumberArea.width(), rect.height())

      if rect.contains(self.viewport().rect()):
        updateLineNumberAreaWidth(0)
    self.updateRequest.connect(updateLineNumberArea)

    def highlightCurrentLine():
      extraSelections = []
      if True: #not self.isReadOnly():
        selection = QtGui.QTextEdit.ExtraSelection()

        lineColor = QtGui.QColor(QtCore.Qt.yellow).lighter(160)

        selection.format.setBackground(lineColor)
        selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        extraSelections.append(selection)
      self.setExtraSelections(extraSelections);
    self.cursorPositionChanged.connect(highlightCurrentLine)

    updateLineNumberAreaWidth(0)
    highlightCurrentLine()

  def resizeEvent(self, event):
    QtGui.QWidget.resizeEvent(self, event)
    cr = self.contentsRect()
    self.__lineNumberArea.setGeometry(
      QtCore.QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height())
      )

  def lineNumberAreaWidth(self):
    digits = 1
    max = self.blockCount()
    if max < 1:
      max = 1
    while max >= 10:
      max = max / 10
      digits = digits + 1
    return 3 + self.fontMetrics().width('9') * digits + 3

  def lineNumberAreaPaintEvent(self, event):
    lineNumberArea = self.__lineNumberArea
    painter = QtGui.QPainter(lineNumberArea)
    painter.fillRect(event.rect(), QtCore.Qt.lightGray)
    block = self.firstVisibleBlock()
    blockNumber = block.blockNumber()
    top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
    bottom = top + int(self.blockBoundingRect(block).height())
    while block.isValid() and top <= event.rect().bottom():
      if block.isVisible() and bottom >= event.rect().top():
        blockNumberText = str(blockNumber + 1)
        painter.setPen(QtCore.Qt.black)
        painter.drawText(
          0, top,
          lineNumberArea.width() - 3, self.fontMetrics().height(),
          QtCore.Qt.AlignRight, blockNumberText
          )
      block = block.next()
      top = bottom
      bottom = top + int(self.blockBoundingRect(block).height())
      blockNumber = blockNumber + 1

  def moveToLine(self, lineNumber):
    document = self.document()
    block = document.findBlockByLineNumber(lineNumber-1)
    textCursor = self.textCursor()
    textCursor.setPosition(block.position())
    self.setTextCursor(textCursor)

  def setFrame(self, frame):
    compileUnit = frame.GetCompileUnit()
    fileSpec = compileUnit.GetFileSpec()
    filename = fileSpec.GetFilename()
    if filename:
      if not filename in self.__files:
        f = open(filename, 'r')
        contents = f.read()
        f.close()
        self.__files[filename] = contents
      else:
        contents = self.__files[filename]
      self.setPlainText(contents)
      lineEntry = frame.GetLineEntry()
      line = lineEntry.GetLine()
      self.moveToLine(line)
    else:
      self.setPlainText("")

codeWidget = CodeWidget()
codeWidget.setReadOnly(True)

class DisassemblyWidget(QtGui.QPlainTextEdit):
  def __init__(self, parent=None):
    QtGui.QPlainTextEdit.__init__(self, parent)

    self.setFont(font)
    self.setReadOnly(True)

  def frame(self):
    return self.__frame

  def setFrame(self, frame):
    self.__frame = frame
    function = frame.GetFunction()
    instructions = function.GetInstructions(target)
    contents = ""
    count = instructions.GetSize()
    for i in range(0, count):
      instruction = instructions.GetInstructionAtIndex(i)
      contents += str(instruction)
      contents += "\n"
    self.setPlainText(contents)

disassemblyWidget = DisassemblyWidget()

class ValueWidgetItem(QtGui.QTreeWidgetItem):
  def __init__(self):
    QtGui.QTreeWidgetItem.__init__(self)

    self.setFont(0, font)
    self.setFont(1, font)
    self.setFont(2, font)

    self.__staticColor = QtGui.QColor(QtCore.Qt.white)
    self.__dynamicColor = QtGui.QColor(QtCore.Qt.red).lighter(190)

  def value(self):
    return self.__value

  def setValue(self, value):
    self.setText(0, value.GetName())
    self.setText(1, value.GetTypeName())
    self.setText(2, value.GetValue())
    if value.GetValueDidChange():
      self.setBackground(2, self.__dynamicColor)
    else:
      self.setBackground(2, self.__staticColor)

    self.takeChildren()
    count = value.GetNumChildren()
    for i in range(0, count):
      childValue = value.GetChildAtIndex(i)
      childValueWidgetItem = ValueWidgetItem()
      childValueWidgetItem.setValue(childValue)
      self.addChild(childValueWidgetItem)

class LocalsWidget(QtGui.QTreeWidget):
  def __init__(self):
    QtGui.QTreeWidget.__init__(self)

    self.setIndentation(12)
    self.setHeaderLabels([
      "Name",
      "Type",
      "Value"
    ])

  def frame(self):
    return self.__frame

  def setFrame(self, frame):
    self.__frame = frame
    includeArguments = True
    includeLocals = True
    includeStatics = True
    in_scope_only = True
    variables = frame.GetVariables(
      includeArguments,
      includeLocals,
      includeStatics,
      in_scope_only
      )
    count = variables.GetSize()
    for i in range(0, count):
      value = variables.GetValueAtIndex(i)
      if i < self.topLevelItemCount():
        valueWidgetItem = self.topLevelItem(i)
      else:
        valueWidgetItem = ValueWidgetItem()
        self.addTopLevelItem(valueWidgetItem)
      valueWidgetItem.setValue(value)
    while self.topLevelItemCount() > count:
      self.takeTopLevelItem(count)
    self.resizeColumnToContents(0)
    self.resizeColumnToContents(1)

localsWidget = LocalsWidget()

class RegistersWidget(QtGui.QTreeWidget):
  def __init__(self):
    QtGui.QTreeWidget.__init__(self)

    self.setIndentation(12)
    self.setHeaderLabels([
      "Name",
      "Type",
      "Value"
    ])

  def frame(self):
    return self.__frame

  def setFrame(self, frame):
    self.__frame = frame
    registers = frame.GetRegisters()
    count = registers.GetSize()
    for i in range(0, count):
      value = registers.GetValueAtIndex(i)
      if i < self.topLevelItemCount():
        valueWidgetItem = self.topLevelItem(i)
      else:
        valueWidgetItem = ValueWidgetItem()
        self.addTopLevelItem(valueWidgetItem)
      valueWidgetItem.setValue(value)
    while self.topLevelItemCount() > count:
      self.takeTopLevelItem(count)
    self.resizeColumnToContents(0)
    self.resizeColumnToContents(1)

registersWidget = RegistersWidget()

class StackWidgetItem(QtGui.QTreeWidgetItem):
  def __init__(self):
    QtGui.QTreeWidgetItem.__init__(self)
    self.setFont(0, font)
    self.setFont(1, font)
    self.setTextAlignment(1, QtCore.Qt.AlignRight)
    self.setFont(2, font)

  def frame(self):
    return self.__frame

  def setFrame(self, frame):
    self.__frame = frame
    lineEntry = frame.GetLineEntry()
    line = lineEntry.GetLine()
    self.setText(0, "%d" % frame.GetFrameID())
    self.setText(1, "0x%x" % frame.GetPC())
    self.setText(2, "%s:%d" % (frame.GetFunctionName(), line))

class StackWidget(QtGui.QTreeWidget):
  def __init__(
    self,
    codeWidget,
    disassemblyWidget,
    localsWidget,
    registersWidget
    ):
    QtGui.QTreeWidget.__init__(self)

    self.__codeWidget = codeWidget
    self.__disassemblyWidget = disassemblyWidget
    self.__localsWidget = localsWidget
    self.__registersWidget = registersWidget

    self.setIndentation(0)
    self.setHeaderLabels([
      "#",
      "PC",
      "Function"
    ])

    def currentItemChanged(newItem, oldItem):
      self.updateFrame()
    self.currentItemChanged.connect(currentItemChanged)

  def updateFrame(self):
    frame = self.currentItem().frame()
    self.__codeWidget.setFrame(frame)
    self.__disassemblyWidget.setFrame(frame)
    self.__localsWidget.setFrame(frame)
    self.__registersWidget.setFrame(frame)

  def setThread(self, thread):
    count = thread.GetNumFrames()
    for i in range(0, count):
      frame = thread.GetFrameAtIndex(i)
      if i < self.topLevelItemCount():
        stackWidgetItem = self.topLevelItem(i)
      else:
        stackWidgetItem = StackWidgetItem()
        self.addTopLevelItem(stackWidgetItem)
      stackWidgetItem.setFrame(frame)
    while self.topLevelItemCount() > count:
      self.takeTopLevelItem(count)

    if self.topLevelItemCount() > 0:
      self.setCurrentItem(self.topLevelItem(0))
    self.resizeColumnToContents(0)
    self.resizeColumnToContents(1)
    self.updateFrame()

stackWidget = StackWidget(
  codeWidget,
  disassemblyWidget,
  localsWidget,
  registersWidget
  )

lineEdit = QtGui.QLineEdit()

class OutputDisplay(QtGui.QTextEdit):
  def __init__(self, parent=None):
    QtGui.QTextEdit.__init__(self, parent)
    self.setFont(font)

  def appendCommand(self, text):
    self.setTextColor(QtCore.Qt.blue)
    cursor = self.textCursor()
    cursor.insertText("> " + text + "\n")

  def appendDebuggerOutput(self, text):
    self.setTextColor(QtCore.Qt.green)
    cursor = self.textCursor()
    cursor.insertText(text + "\n")

  def appendDebuggerErrorOutput(self, text):
    self.setTextColor(QtCore.Qt.red)
    cursor = self.textCursor()
    cursor.insertText(text + "\n")

  def appendProgramOutput(self, text):
    self.setTextColor(QtCore.Qt.black)
    cursor = self.textCursor()
    cursor.insertText(text + "\n")

outputDisplay = OutputDisplay()

centralLayout = QtGui.QVBoxLayout()
centralLayout.addWidget(codeWidget)
centralLayout.addWidget(outputDisplay)
centralLayout.addWidget(lineEdit)

centralWidget = QtGui.QWidget()
centralWidget.setLayout(centralLayout)

stackWidget_dockWidget = QtGui.QDockWidget()
stackWidget_dockWidget.setTitleBarWidget(QtGui.QLabel("Stack"))
stackWidget_dockWidget.setWidget(stackWidget)

disassemblyWidget_dockWidget = QtGui.QDockWidget()
disassemblyWidget_dockWidget.setTitleBarWidget(QtGui.QLabel("Disassembly"))
disassemblyWidget_dockWidget.setWidget(disassemblyWidget)

localsWidget_dockWidget = QtGui.QDockWidget()
localsWidget_dockWidget.setTitleBarWidget(QtGui.QLabel("Locals"))
localsWidget_dockWidget.setWidget(localsWidget)

registersWidget_dockWidget = QtGui.QDockWidget()
registersWidget_dockWidget.setTitleBarWidget(QtGui.QLabel("Registers"))
registersWidget_dockWidget.setWidget(registersWidget)

mainWindow = QtGui.QMainWindow()
mainWindow.setCentralWidget(centralWidget)
mainWindow.addDockWidget(QtCore.Qt.TopDockWidgetArea, registersWidget_dockWidget)
mainWindow.addDockWidget(QtCore.Qt.TopDockWidgetArea, localsWidget_dockWidget)
mainWindow.addDockWidget(QtCore.Qt.LeftDockWidgetArea, stackWidget_dockWidget)
mainWindow.addDockWidget(QtCore.Qt.RightDockWidgetArea, disassemblyWidget_dockWidget)
mainWindow.show()

command_interpreter = debugger.GetCommandInterpreter()

print "Setting a breakpoint at '%s'" % "main"
main_bp = target.BreakpointCreateByName("main", target.GetExecutable().GetFilename())

print "Lauing process with arguments " + str(arguments)
process = target.LaunchSimple (arguments, None, os.getcwd())
if not process or process.GetProcessID() == lldb.LLDB_INVALID_PROCESS_ID:
  print "Launch failed!"
  sys.exit(1)

pid = process.GetProcessID()
listener = debugger.GetListener()

def handleDebuggerEvents():
  done = False
  if not done:
    event = lldb.SBEvent()
    if listener.GetNextEvent(event):
      if event.GetBroadcaster().GetName() == "lldb.process":
        state = lldb.SBProcess.GetStateFromEvent (event)
        if state == lldb.eStateInvalid:
            # Not a state event
            print 'process event = %s' % (event)
        else:
            print "process state changed event: %s" % (lldb.SBDebugger.StateAsCString(state))
            if state == lldb.eStateStopped:
              print "process %u stopped" % (pid)
              for thread in process:
                stackWidget.setThread(thread)
            elif state == lldb.eStateExited:
                exit_desc = process.GetExitDescription()
                if exit_desc:
                    print "process %u exited with status %u: %s" % (pid, process.GetExitStatus (), exit_desc)
                else:
                    print "process %u exited with status %u" % (pid, process.GetExitStatus ())
                # run_commands (command_interpreter, options.exit_commands)
                done = True
            elif state == lldb.eStateCrashed:
                print "process %u crashed" % (pid)
                print_threads (process, options)
                # run_commands (command_interpreter, options.crash_commands)
                done = True
            elif state == lldb.eStateDetached:
                print "process %u detached" % (pid)
                done = True
            elif state == lldb.eStateRunning:
              # process is running, don't say anything, we will always get one of these after resuming
              print "process %u resumed" % (pid)
            elif state == lldb.eStateUnloaded:
                print "process %u unloaded, this shouldn't happen" % (pid)
                done = True
            elif state == lldb.eStateConnected:
                print "process connected"
            elif state == lldb.eStateAttaching:
                print "process attaching"
            elif state == lldb.eStateLaunching:
                print "process launching"
      else:
          print 'Non-process event = %s' % (event)
  process_stdout = process.GetSTDOUT(1024)
  if process_stdout:
    outputDisplay.appendProgramOutput(process_stdout)
    while process_stdout:
      process_stdout = process.GetSTDOUT(1024)
      outputDisplay.appendProgramOutput(process_stdout)
  process_stderr = process.GetSTDERR(1024)
  if process_stderr:
    outputDisplay.appendProgramOutput(process_stderr)
    while process_stderr:
      process_stderr = process.GetSTDERR(1024)
      outputDisplay.appendProgramOutput(process_stderr)

def executeCommand():
  command = str(lineEdit.text())
  outputDisplay.appendCommand(command)
  lineEdit.clear()
  return_obj = lldb.SBCommandReturnObject()
  command_interpreter.HandleCommand(command, return_obj)
  if return_obj.Succeeded():
    outputDisplay.appendDebuggerOutput(return_obj.GetOutput())
  else:
    outputDisplay.appendDebuggerErrorOutput(return_obj.GetError())
lineEdit.returnPressed.connect(executeCommand)
lineEdit.setFocus()

timer = QtCore.QTimer()
timer.setInterval(100)
timer.timeout.connect(handleDebuggerEvents)
timer.start()

sys.exit(app.exec_())

