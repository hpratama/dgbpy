#__________________________________________________________________________
#
# (C) dGB Beheer B.V.; (LICENSE) http://opendtect.org/OpendTect_license.txt
# Author:        A. Huck
# Date:          Jan 2019
#
# _________________________________________________________________________a

import sys
import argparse
import logging

from bokeh.layouts import row, column, layout
from bokeh.models import Spacer
from bokeh.models.widgets import (Button, CheckboxGroup, Panel, Select, Slider,
                                  Tabs, TextInput)
from bokeh.plotting import curdoc
from bokeh.util import logconfig

from odpy import common as odcommon
from dgbpy import mlapply as dgbmlapply

parser = argparse.ArgumentParser(prog='PROG',description='Select parameters for machine learning model training')
parser.add_argument('-v','--version',action='version',version='%(prog)s 1.0')
parser.add_argument('h5file',type=argparse.FileType('r'),help='HDF5 file containing the training data')
datagrp = parser.add_argument_group('Data')
datagrp.add_argument('--dataroot',dest='dtectdata',metavar='DIR',nargs=1,
                     help='Survey Data Root')
datagrp.add_argument('--survey',dest='survey',nargs=1,
                     help='Survey name')
odappl = parser.add_argument_group('OpendTect application')
odappl.add_argument('--dtectexec',metavar='DIR',nargs=1,help='Path to OpendTect executables')
odappl.add_argument('--qtstylesheet',metavar='qss',nargs=1,type=argparse.FileType('r'),
                    help='Qt StyleSheet template')
loggrp = parser.add_argument_group('Logging')
loggrp.add_argument('--proclog',dest='logfile',metavar='file',nargs='?',
                    type=argparse.FileType('a'),
                    default=sys.stdout,help='Progress report output')
loggrp.add_argument('--syslog',dest='sysout',metavar='stdout',nargs='?',type=argparse.FileType('a'),
                        default=sys.stdout,help='Standard output')
args = vars(parser.parse_args())
odcommon.initLogging(args)

but_width = 80
but_height = 20
but_spacer = 5

traintabnm = 'Training'
paramtabnm = 'Parameters'

trainpanel = Panel(title=traintabnm)
parameterspanel = Panel(title=paramtabnm)
mainpanel = Tabs(tabs=[trainpanel,parameterspanel])

ML_PLFS = [('keras','Keras (tensorflow)'),
           ('scikit','Scikit-learn')]
platformfld = Select(title="Machine learning platform:",options=ML_PLFS)
outputnmfld = TextInput(value='<new model>',title='Output model:')

keras_dict = {
  'decimation': None,
  'iters': 15,
  'epoch': 15,
  'batch': 16,
  'patience': 10
}
scikit_dict = {
  'nb': 3
}

def setActiveTab( tabspanelwidget, tabnm ):
  tabs = tabspanelwidget.tabs
  for i in range( len(tabs) ):
    if tabs[i].title == tabnm:
      tabspanelwidget.active = i
      return

def integerListContains( listobj, index ):
  for itm in listobj:
    if itm == index:
      return True
  return False

def doDecimate( fldwidget, index=0 ):
  return integerListContains( fldwidget.active, index )

def doKeras():
  return platformfld.value == ML_PLFS[0][0]

def doScikit():
  return platformfld.value == ML_PLFS[1][0]

def setTraingTabCB():
  setActiveTab( mainpanel, traintabnm )

def setParsTabCB():
  setActiveTab( mainpanel, paramtabnm )

def getKerasParsGrp():
  decimatefld = CheckboxGroup( labels=['Decimate input'], active=[] )
  iterfld = Slider(start=1,end=100,value=keras_dict['iters'],step=1,
              title='Iterations')
  epochfld = Slider(start=1,end=100,value=keras_dict['epoch'],step=1,
              title='Epochs')
  batchfld = Slider(start=1,end=100,value=keras_dict['batch'],step=1,
            title='Number of Batch')
  patiencefld = Slider(start=1,end=100,value=keras_dict['patience'],step=1,
                title='Patience')
  return (decimatefld,iterfld,epochfld,batchfld,patiencefld,{
    'tabname': 'Keras',
    'grp' : column(decimatefld,iterfld,epochfld,batchfld,patiencefld)
  })

def getScikitParsGrp():
  nbparfld = Slider(start=1,end=100,value=scikit_dict['nb'],step=1,
              title='Number')
  return (nbparfld,{
    'tabname': 'Scikit-learn',
    'grp': column(nbparfld)
  })

def getButtonsGrp():
  runbut = Button(label="Run",button_type="success",
                  width=but_width,height=but_height)
  stopbut = Button(label="Stop",disabled=True,width=but_width,height=but_height)
  return ( runbut, stopbut,
           row(Spacer(width=110),runbut,Spacer(width=but_spacer),stopbut) )

platformparsbut = Button(label=paramtabnm,width=but_width,height=but_height)

(decimatefld,iterfld,epochfld,batchfld,patiencefld,kerasparsgrp) = getKerasParsGrp()
(nbparfld,scikitparsgrp) = getScikitParsGrp()

parsgroups = (kerasparsgrp,scikitparsgrp)
tabparslist = list()
for parsgrp in parsgroups:
  tabparslist.append( Panel(title=parsgrp['tabname'],child=parsgrp['grp']) )
tabpars = Tabs(tabs=tabparslist)
parsbackbut = Button(label="Back",width=but_width,height=but_height)

(runbut,stopbut,buttonsgrp) = getButtonsGrp()
trainpanel.child = column( platformfld, platformparsbut, outputnmfld,
                           buttonsgrp )

parameterspanel.child = column( tabpars, parsbackbut )

def mlchgCB( attrnm, old, new):
  selParsGrp( new )

def selParsGrp( platformnm ):
  for platform,parsgroup in zip(ML_PLFS,parsgroups):
    if platform[0] == platformnm:
      setActiveTab( tabpars, parsgroup['tabname'] )
      return

def decimateCB( widgetactivelist ):
  decimate = integerListContains( widgetactivelist, 0 )
  iterfld.disabled = not decimate

def getKerasDict():
  ret = {
    'decimation': None,
    'num_tot_iterations': 1,
    'epochs': epochfld.value,
    'batch_size': batchfld.value,
    'opt_patience': patiencefld.value 
  }
  if doDecimate(decimatefld):
    ret['decimation'] = True
    ret['num_tot_iterations'] = iterfld.value
  return ret

def getScikitDict():
  return {
    'testpar': nbparfld.value
  }

def getParams():
  if doKeras():
    return getKerasDict()
  elif doScikit():
    return getScikitDict()
  return {}

def acceptOK():
  runbut.disabled = True
  stopbut.disabled = False
  success = dgbmlapply.doTrain( getParams(), outputnmfld.value, args )
  if success:
    odcommon.log_msg( "Deeplearning Training Module Finished" )
    odcommon.log_msg( "" )
    odcommon.log_msg( "Finished batch processing." )
    odcommon.log_msg( "" )
  rejectOK()

def rejectOK():
  runbut.disabled = False
  stopbut.disabled = True

platformfld.on_change('value', mlchgCB)
platformparsbut.on_click(setParsTabCB)
runbut.on_click(acceptOK)
stopbut.on_click(rejectOK)
decimatefld.on_click(decimateCB)
parsbackbut.on_click(setTraingTabCB)

def initWin():
  platformfld.value = ML_PLFS[0][0]
  mlchgCB( 'value', 0, platformfld.value )
  decimateCB( decimatefld.active )

initWin()
curdoc().add_root(mainpanel)