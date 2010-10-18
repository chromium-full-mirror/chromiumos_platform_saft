#!/usr/bin/python
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''A rudimentary X based screen control module.

It allows to create an X window and to print a text message on the screen even
when the computer is locked. To be able to take over a locked computer, a
separate X server needs to be run, available implicitly through the
environment variable DISPLAY.
'''

import gtk
import pango
import threading
import warnings

class PyApp(gtk.Window):
    '''A class to instantiate a gtk Window.

    Attributes:
      fontdesc - a pango font description, uses 'Droid Sans' 20 units high,
                 which is exactly right for a typical ChromeOs device.
      '''
    def __init__(self, font="Droid Sans 20"):
        super(PyApp, self).__init__()
        gtk.gdk.threads_init()
        self.fontdesc = pango.FontDescription(font)
        self.connect("destroy", gtk.main_quit)

    def set_text(self, text):
        '''Prepare text to be displayed when this window is activated.'''
        label = gtk.Label(text)
        label.modify_font(self.fontdesc)
        fix = gtk.Fixed()
        fix.put(label, 15, 5)

        self.add(fix)
        self.set_position(gtk.WIN_POS_CENTER)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.show_all()

class GraphThread(threading.Thread):
    '''A thread to display the GTK window on.'''

    def __init__(self):
        super(GraphThread, self).__init__()
        self.gtk_window = PyApp()

    def display_text(self, text):
        '''Set text to display and start the thread.

        Starting the thread will cause the text to show up in the window.
        '''
        self.gtk_window.set_text(text)
        self.start()

    def run(self):
        '''gtk worker thread (causing the text to show up).'''
        gtk.main()

    def stop(self):
        '''Destroy the window when stopping the graphics control thread.'''
        self.gtk_window.destroy()
