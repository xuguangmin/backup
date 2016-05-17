#!/usr/bin/env python
#encoding:utf-8


try:
    import pygtk
    pygtk.require("2.0")
except Exception, detail:
    print "You do not have a recent version of GTK"

try:
    import os
    import sys
    import commands
    import gtk
    import gtk.glade
    import gettext
    import threading
    import tarfile
    import stat
    import shutil
    import hashlib
    from time import strftime, localtime, sleep
    import apt
    import subprocess
    from user import home
    import tempfile
    import apt.progress.gtk2
    import string
    import psutil
    import re
    import logging
      
    from logging.handlers import  TimedRotatingFileHandler 
    import traceback

except Exception, detail:
    print "You do not have the required dependencies"

# i18n
gettext.install("nfsbackup", "/usr/share/nfsbackup/locale")
#gettext.install("nfsbackup", "../../../share/nfsbackup/locale")

# i18n for menu item
menuName = _("Backup Tool")
menuComment = _("Make a backup of your home directory")

class LogManagement():
    def __init__(self, logfile="/var/log/nfsbackup/nfsBackup.log", logger="NFSBackup", logLevel=logging.DEBUG, consoleLevel=logging.INFO, maxBytes=10*1024*1024, logfilecount=20):
        #from logging.handlers import RotatingFileHandler  
        self.logFilePath = logfile  
        self.logger = logging.getLogger(logger)  
        self.logger.setLevel(logLevel)  
        
        self.logfile_handler = TimedRotatingFileHandler(self.logFilePath, when="d", interval=1, backupCount=logfilecount)
        self.logfile_formatter = logging.Formatter('%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')  
        self.logfile_handler.setFormatter(self.logfile_formatter)  
        
        #定义一个StreamHandler，将INfo级别或更高的日志信息打印到标准错误
        self.console_handler = logging.StreamHandler()
        self.console_handler.setLevel(consoleLevel)
        self.console_formatter = logging.Formatter('%(threadName)-10s - %(levelname)-8s %(message)s')
        self.console_handler.setFormatter(self.console_formatter)
        
        self.logger.addHandler(self.logfile_handler)  
        self.logger.addHandler(self.console_handler)  

    def nfs_info(self, oriStr=""):
        self.logger.info(oriStr)

    def nfs_error(self, oriStr=""):
        self.logger.error(oriStr)

class TarFileMonitor():
    ''' Bit of a hack but I can figure out what tarfile is doing now.. (progress wise) '''
    def __init__(self, target, callback):
        self.counter = 0
        self.size = 0
        self.f = open(target, "rb")
        self.name = self.f.name
        self.fileno = self.f.fileno
        self.callback = callback
        self.size = os.path.getsize(target)
    def read(self, size=None):
        bytes = 0
        if(size is not None):
            bytes = self.f.read(size)
            if(bytes):
                self.counter += len(bytes)
                self.callback(self.counter, self.size)
        else:
            bytes = self.f.read()
            if(bytes is not None):
                self.counter += len(bytes)
                self.callback(self.counter, self.size)
        return bytes
    def close(self):
        self.f.close()

''' Funkai little class for abuse-safety. all atrr's are set from file '''
class mINIFile():
    def load_from_string(self, line):
        if(line.find(":")):
            l = line.split(":")
            if(len(l) >= 2):
                tmp = ":".join(l[1:]).rstrip("\r\n")
                setattr(self, l[0], tmp)
        elif(line.find("=")):
            l = line.split("=")
            if(len(l) >= 2):
                tmp = "=".join(l[1:]).rstrip("\r\n")
                setattr(self, l[0], tmp)

    def load_from_list(self, list):
        for line in list:
            self.load_from_string(line)
    def load_from_file(self, filename):
        try:
            fi = open(filename, "r")
            self.load_from_list(fi.readlines())
            fi.close()
        except:
            pass
''' Handy. Makes message dialogs easy :D '''
class MessageDialog(apt.progress.gtk2.GOpProgress):

    def __init__(self, title, message, style):
        self.title = title
        self.message = message
        self.style = style

    ''' Show me on screen '''
    def show(self):

        dialog = gtk.MessageDialog(None, gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT, self.style, gtk.BUTTONS_OK, self.message)
        dialog.set_title(_("Backup Tool"))
        dialog.set_position(gtk.WIN_POS_CENTER)
        dialog.run()
        dialog.destroy()

''' The main class of the app '''
class MintBackup:

    ''' New MintBackup '''
    def __init__(self):
        self.glade = '/usr/lib/nfsbackup/nfsBackup.glade'
        #self.glade = 'nfsBackup.glade'
        self.wTree = gtk.glade.XML(self.glade, 'main_window')
        self.wTree.get_widget("main_window").set_icon_from_file("/usr/lib/nfsbackup/icon.png")
        self.current_userpath = ""
        # handle command line filenames
        if(len(sys.argv) > 1):
            if(len(sys.argv) == 2):
                self.current_userpath = sys.argv[1]
                #self.wTree.get_widget("filechooserbutton_restore_source").set_filename(filebackup)
            else:
                print "usage: " + sys.argv[0] + " filename.backup"
                sys.exit(1)
        else:
            self.wTree.get_widget("notebook1").set_current_page(0)
        # log 
        self.log = LogManagement()
        # inidicates whether an operation is taking place.
        self.operating = False

        # preserve permissions?
        self.preserve_perms = True
        # preserve times?
        self.preserve_times = True
        # post-check files?
        self.postcheck = True
        # follow symlinks?
        self.follow_links = False
        # error?
        self.error = None
        # tarfile
        self.tar = None
        self.restore_source = ""
        self.backup_dest = ""
        self.backup_timer_dest = ""
        self.conf_dest = ""
        self.conf_type = 0
#####################################################
        self.boot_install_dir = "/boot"
        self.boot_cfg = "/boot/grub/grub.cfg"

        self.system_source = None
        self.system_dest_dir = "/"
        self.system_restore_stat = False
        self.system_backup_stat = False
        self.systembackup_timer = False
        self.remove_systembackup = False
        self.month_periodic = False
####################################################
        self.conf_type_name = {'0':_("Backup user configure"),
                          '1':_("Backup system configure"),
                          '2':_("Backup all configure"),
                          '3':_("Restore user configure"),
                          '4':_("Restore system configure"),
                          '5':_("Restore all configure")}
        self.conf_type_tarname = {'0':"userconf",
                          '1':"sysconf",
                          '2':"allconf"}

        self.restore_archive = False
        # by default we set a periodic timer
        self.set_periodic = True
        self.update_flag = False
        self.timer_command = ""

        # page 0
        self.wTree.get_widget("button_backup_files").connect("clicked", self.wizard_buttons_cb, 1)
        self.wTree.get_widget("button_restore_files").connect("clicked", self.wizard_buttons_cb, 6)
        self.wTree.get_widget("button_backup_packages").connect("clicked", self.wizard_buttons_cb, 10)
        self.wTree.get_widget("button_restore_packages").connect("clicked", self.wizard_buttons_cb, 14)
        self.wTree.get_widget("button_backup_timer").connect("clicked", self.wizard_buttons_cb, 2)
        self.wTree.get_widget("button_backup_restore_conf").connect("clicked", self.wizard_buttons_cb, 19)
        self.wTree.get_widget("button_backup_system").connect("clicked", self.wizard_buttons_cb, 25)
        self.wTree.get_widget("button_restore_system").connect("clicked", self.wizard_buttons_cb, 29)

        # set up backup page 1 (source/dest/options)
        # Displayname, [tarfile mode, file extension]
        self.iconTheme = gtk.icon_theme_get_default()
        self.dirIcon = self.iconTheme.load_icon("folder", 16, 0)
        self.fileIcon = self.iconTheme.load_icon("document-new", 16, 0)

        ren = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn("", ren)
        column.add_attribute(ren, "pixbuf", 1)
        self.wTree.get_widget("treeview_source").append_column(column)
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Add paths"), ren)
        column.add_attribute(ren, "text", 0)
        self.wTree.get_widget("treeview_source").append_column(column)
        self.wTree.get_widget("treeview_source").set_model(gtk.ListStore(str, gtk.gdk.Pixbuf, str))

        self.wTree.get_widget("button_addfile").connect("clicked", self.add_file)
        self.wTree.get_widget("button_addfolder").connect("clicked", self.add_folder)
        self.wTree.get_widget("button_remove").connect("clicked", self.remove_exclude)
        self.wTree.get_widget("button_backup_dest").connect("clicked", self.set_entry1)  

        comps = gtk.ListStore(str,str,str)
        comps.append([_("Preserve structure"), None, None])
        # file extensions nfsBackup specific
        comps.append([_(".tar file"), "w", ".tar"])
        comps.append([_(".tar.bz2 file"), "w:bz2", ".tar.bz2"])
        comps.append([_(".tar.gz file"), "w:gz", ".tar.gz"])
        self.wTree.get_widget("combobox_compress").set_model(comps)
        self.wTree.get_widget("combobox_compress").set_active(0)

        # backup overwrite options
        overs = gtk.ListStore(str)
        overs.append([_("Never")])
        overs.append([_("Size mismatch")])
        overs.append([_("Modification time mismatch")])
        overs.append([_("Checksum mismatch")])
        overs.append([_("Always")])
        self.wTree.get_widget("combobox_delete_dest").set_model(overs)
        self.wTree.get_widget("combobox_delete_dest").set_active(3)

        # advanced options
        self.wTree.get_widget("checkbutton_integrity").set_active(self.postcheck)
        self.wTree.get_widget("checkbutton_integrity").connect("clicked", self.handle_checkbox)
        self.wTree.get_widget("checkbutton_perms").set_active(self.preserve_perms)
        self.wTree.get_widget("checkbutton_perms").connect("clicked", self.handle_checkbox)
        self.wTree.get_widget("checkbutton_times").set_active(self.preserve_times)
        self.wTree.get_widget("checkbutton_times").connect("clicked", self.handle_checkbox)
        self.wTree.get_widget("checkbutton_links").set_active(self.follow_links)
        self.wTree.get_widget("checkbutton_links").connect("clicked", self.handle_checkbox)

        # set up backup-timer page
        # set up page 17 (source/dest/options)
        # Displayname, [tarfile mode, file extension]
        self.iconTheme = gtk.icon_theme_get_default()
        self.dirIcon = self.iconTheme.load_icon("folder", 16, 0)
        self.fileIcon = self.iconTheme.load_icon("document-new", 16, 0)

        ren = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn("", ren)
        column.add_attribute(ren, "pixbuf", 1)
        self.wTree.get_widget("treeview_source1").append_column(column)
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Add paths"), ren)
        column.add_attribute(ren, "text", 0)
        self.wTree.get_widget("treeview_source1").append_column(column)
        self.wTree.get_widget("treeview_source1").set_model(gtk.ListStore(str, gtk.gdk.Pixbuf, str))

        self.wTree.get_widget("button_addfile1").connect("clicked", self.add_file)
        self.wTree.get_widget("button_addfolder1").connect("clicked", self.add_folder)
        self.wTree.get_widget("button_remove1").connect("clicked", self.remove_exclude)
        self.wTree.get_widget("button_backup_dest2").connect("clicked", self.set_entry1)         
        self.wTree.get_widget("button_addsystem1").connect("clicked", self.add_systembackup_timer) 

        comps = gtk.ListStore(str,str,str)
        comps.append([_("Preserve structure always overwrite"), None, None])
        # file extensions nfsBackup specific
        comps.append([_(".tar file not overwrite"), "w", ".tar"])
        self.wTree.get_widget("combobox_compress1").set_model(comps)
        self.wTree.get_widget("combobox_compress1").set_active(0)

        t = self.wTree.get_widget("treeview_backup_timer")
        self.wTree.get_widget("button_create_timer").connect("clicked", self.add_backuptimer)
        self.wTree.get_widget("button_delete_timer").connect("clicked", self.remove_backuptimer)
        self.wTree.get_widget("button_remove_system").connect("clicked", self.remove_systembackup_timer)
        
        c2 = gtk.TreeViewColumn(None, gtk.CellRendererText(), markup=0)
        t.append_column(c2)

        #set timer - hour
        comps = gtk.ListStore(str,str,str)
        comps.append(["0", None, None])
        comps.append(["1", None, None])
        comps.append(["2", None, None])
        comps.append(["3", None, None])
        comps.append(["4", None, None])
        comps.append(["5", None, None])
        comps.append(["6", None, None])
        comps.append(["7", None, None])
        comps.append(["8", None, None])
        comps.append(["9", None, None])
        comps.append(["10", None, None])
        comps.append(["11", None, None])
        comps.append(["12", None, None])
        comps.append(["13", None, None])
        comps.append(["14", None, None])
        comps.append(["15", None, None])
        comps.append(["16", None, None])
        comps.append(["17", None, None])
        comps.append(["18", None, None])
        comps.append(["19", None, None])
        comps.append(["20", None, None])
        comps.append(["21", None, None])
        comps.append(["22", None, None])
        comps.append(["23", None, None])
        self.wTree.get_widget("combobox_hour").set_model(comps)
        self.wTree.get_widget("combobox_hour").set_active(13)

        #set timer - minute
        comps = gtk.ListStore(str,str,str)
        minute1 = ['0', '1', '2', '3', '4', '5']
        minute2 = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
        for m1 in minute1:
            for m2 in minute2:
                comps.append([m1+m2, None, None])
        self.wTree.get_widget("combobox_minute").set_model(comps)
        self.wTree.get_widget("combobox_minute").set_active(0)     

        #set timer - month
        comps = gtk.ListStore(str,str,str)
        comps.append(["1", None, None])
        comps.append(["2", None, None])
        comps.append(["3", None, None])
        comps.append(["4", None, None])
        comps.append(["5", None, None])
        comps.append(["6", None, None])
        comps.append(["7", None, None])
        comps.append(["8", None, None])
        comps.append(["9", None, None])
        comps.append(["10", None, None])
        comps.append(["11", None, None])
        comps.append(["12", None, None])
        self.wTree.get_widget("combobox_month").set_model(comps)
        self.wTree.get_widget("combobox_month").set_active(0)  
        self.wTree.get_widget("combobox_month").set_sensitive(False)

        #set timer - day
        comps = gtk.ListStore(str,str,str)
        day = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 
               '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', 
               '20', '21', '22', '23', '24', '25', '26', '27', '28', '29', 
               '30', '31']
        for d in day:
            comps.append([d, None, None])
        self.wTree.get_widget("combobox_day").set_model(comps)
        self.wTree.get_widget("combobox_day").set_active(0)
        self.wTree.get_widget("combobox_day").set_sensitive(False)
 
         #set timer - day1        
        comps = gtk.ListStore(str,str,str)
        day1 = ['1', '2', '3', '4', '5', '6', '7', '8', '9',
               '10', '11', '12', '13', '14', '15', '16', '17', '18', '19',
               '20', '21', '22', '23', '24', '25', '26', '27', '28']
        for d1 in day1:
            comps.append([d1, None, None])
        self.wTree.get_widget("combobox_day1").set_model(comps)
        self.wTree.get_widget("combobox_day1").set_active(0)
        self.wTree.get_widget("combobox_day1").set_sensitive(False)
            
        #set checkbutton_week
        self.wTree.get_widget("radiobutton_onetime").connect("toggled", self.select_periodic)
        self.wTree.get_widget("radiobutton_periodic").connect("toggled", self.select_periodic)
        self.wTree.get_widget("radiobutton_month").connect("toggled", self.select_periodic)

        self.wTree.get_widget("checkbutton_Mon").set_active(True)
        self.wTree.get_widget("checkbutton_Tue").set_active(True)
        self.wTree.get_widget("checkbutton_Wed").set_active(True)
        self.wTree.get_widget("checkbutton_Thu").set_active(True)
        self.wTree.get_widget("checkbutton_Fri").set_active(True)
        self.wTree.get_widget("checkbutton_Sat").set_active(True)
        self.wTree.get_widget("checkbutton_Sun").set_active(True)


        # set up overview page
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Type"), ren)
        column.add_attribute(ren, "markup", 0)
        self.wTree.get_widget("treeview_overview").append_column(column)
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Detail"), ren)
        column.add_attribute(ren, "text", 1)
        self.wTree.get_widget("treeview_overview").append_column(column)

        # Errors treeview for backup
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Path"), ren)
        column.add_attribute(ren, "text", 0)
        self.wTree.get_widget("treeview_backup_errors").append_column(column)
        column = gtk.TreeViewColumn(_("Error"), ren)
        column.add_attribute(ren, "text", 1)
        self.wTree.get_widget("treeview_backup_errors").append_column(column)

        # Errors treeview for restore. yeh.
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Path"), ren)
        column.add_attribute(ren, "text", 0)
        self.wTree.get_widget("treeview_restore_errors").append_column(column)
        column = gtk.TreeViewColumn(_("Error"), ren)
        column.add_attribute(ren, "text", 1)
        self.wTree.get_widget("treeview_restore_errors").append_column(column)
        # model.
        self.errors = gtk.ListStore(str,str)

        # nav buttons
        self.wTree.get_widget("button_back").connect("clicked", self.back_callback)
        self.wTree.get_widget("button_forward").connect("clicked", self.forward_callback)
        self.wTree.get_widget("button_apply").connect("clicked", self.forward_callback)
        self.wTree.get_widget("button_cancel").connect("clicked", self.cancel_callback)
        self.wTree.get_widget("button_about").connect("clicked", self.about_callback)
        self.wTree.get_widget("button_back_main").connect("clicked", self.back_main_callback)

        self.wTree.get_widget("button_back").hide()
        self.wTree.get_widget("button_forward").hide()
        self.wTree.get_widget("button_back_main").hide()
        self.wTree.get_widget("button_back_main").set_sensitive(False)
        self.wTree.get_widget("main_window").connect("destroy", self.cancel_callback)
        self.wTree.get_widget("main_window").set_title(_("Backup Tool"))
        self.wTree.get_widget("main_window").show()

        # open archive button, opens an archive... :P
        self.wTree.get_widget("radiobutton_archive").connect("toggled", self.archive_switch)
        self.wTree.get_widget("radiobutton_dir").connect("toggled", self.archive_switch)
        self.wTree.get_widget("button_restore_sour").connect("clicked", self.set_entry2)
        self.wTree.get_widget("button_restore_sour").set_sensitive(False)
        self.wTree.get_widget("button_restore_dest").connect("clicked", self.set_entry3)


        # Displayname, [tarfile mode, file extension]
        self.iconTheme = gtk.icon_theme_get_default()
        self.dirIcon = self.iconTheme.load_icon("folder", 16, 0)
        self.fileIcon = self.iconTheme.load_icon("document-new", 16, 0)

        ren = gtk.CellRendererPixbuf()
        column = gtk.TreeViewColumn("", ren)
        column.add_attribute(ren, "pixbuf", 1)
        self.wTree.get_widget("treeview_source_restore").append_column(column)
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Add paths"), ren)
        column.add_attribute(ren, "text", 0)
        self.wTree.get_widget("treeview_source_restore").append_column(column)
        self.wTree.get_widget("treeview_source_restore").set_model(gtk.ListStore(str, gtk.gdk.Pixbuf, str))

        self.wTree.get_widget("button_addfile_restore").connect("clicked", self.add_file)
        self.wTree.get_widget("button_addfolder_restore").connect("clicked", self.add_folder)
        self.wTree.get_widget("button_remove_restore").connect("clicked", self.remove_exclude)

        self.wTree.get_widget("combobox_restore_del").set_model(overs)
        self.wTree.get_widget("combobox_restore_del").set_active(3)
        #self.wTree.get_widget("filechooserbutton_backup_source").connect("current-folder-changed", self.save_backup_source)
        #self.wTree.get_widget("filechooserbutton_backup_dest").connect("current-folder-changed", self.save_backup_dest)

        self.wTree.get_widget("combobox_restore_del").set_model(overs)
        self.wTree.get_widget("combobox_restore_del").set_active(3)

        # packages list
        self.wTree.get_widget("button_backup_dest1").connect("clicked", self.set_entry4)
        t = self.wTree.get_widget("treeview_packages")
        self.wTree.get_widget("button_select").connect("clicked", self.set_selection, t, True, False)
        self.wTree.get_widget("button_deselect").connect("clicked", self.set_selection, t, False, False)
        tog = gtk.CellRendererToggle()
        tog.connect("toggled", self.toggled_cb, t)
        c1 = gtk.TreeViewColumn(_("Store?"), tog, active=0)
        c1.set_cell_data_func(tog, self.celldatafunction_checkbox)
        t.append_column(c1)
        c2 = gtk.TreeViewColumn(_("Name"), gtk.CellRendererText(), markup=2)
        t.append_column(c2)

		#choose a destination of backup system
		###########################################################################################

        self.wTree.get_widget("button_backup_dest3").connect("clicked", self.set_entry6)

		###########################################################################################

        # choose a package list
        t = self.wTree.get_widget("treeview_package_list")
        self.wTree.get_widget("button_select_list").connect("clicked", self.set_selection, t, True, True)
        self.wTree.get_widget("button_deselect_list").connect("clicked", self.set_selection, t, False, True)
        self.wTree.get_widget("button_refresh").connect("clicked", self.refresh)
        tog = gtk.CellRendererToggle()
        tog.connect("toggled", self.toggled_cb, t)
        c1 = gtk.TreeViewColumn(_("Install"), tog, active=0, activatable=2)
        c1.set_cell_data_func(tog, self.celldatafunction_checkbox)
        t.append_column(c1)
        c2 = gtk.TreeViewColumn(_("Name"), gtk.CellRendererText(), markup=1)
        t.append_column(c2)
        self.wTree.get_widget("filechooserbutton_package_source").connect("file-set", self.load_package_list_cb)

		####################################################################################################################
	# choose a file for restore system
        self.wTree.get_widget("filechooserbutton_package_source5").connect("file-set", self.load_file_for_restore_system)
		####################################################################################################################


        #set combobox of configure
        comps = gtk.ListStore(str)
        comps.append([_("Backup user configure")])
        comps.append([_("Backup system configure")])
        comps.append([_("Backup all configure")])
        comps.append([_("Restore user configure")])
        comps.append([_("Restore system configure")])
        comps.append([_("Restore all configure")])
        self.wTree.get_widget("combobox_conf").set_model(comps)
        self.wTree.get_widget("combobox_conf").set_active(0)
        self.wTree.get_widget("combobox_conf").connect("changed", self.com_conf_callback)
        self.wTree.get_widget("button_sour_conf").set_sensitive(False)
        self.wTree.get_widget("button_dest_conf").connect("clicked", self.set_entry1)
        self.wTree.get_widget("button_sour_conf").connect("clicked", self.set_entry_sour)

        # set up configure overview page
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Type"), ren)
        column.add_attribute(ren, "markup", 0)
        self.wTree.get_widget("treeview_overview_conf").append_column(column)
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Detail"), ren)
        column.add_attribute(ren, "text", 1)
        self.wTree.get_widget("treeview_overview_conf").append_column(column)

        # Errors treeview for backuping configure
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Path"), ren)
        column.add_attribute(ren, "text", 0)
        self.wTree.get_widget("treeview_backup_errors_conf").append_column(column)
        column = gtk.TreeViewColumn(_("Error"), ren)
        column.add_attribute(ren, "text", 1)
        self.wTree.get_widget("treeview_backup_errors_conf").append_column(column)

        # Errors treeview for restoring configure
        ren = gtk.CellRendererText()
        column = gtk.TreeViewColumn(_("Path"), ren)
        column.add_attribute(ren, "text", 0)
        self.wTree.get_widget("treeview_restore_errors_conf").append_column(column)
        column = gtk.TreeViewColumn(_("Error"), ren)
        column.add_attribute(ren, "text", 1)
        self.wTree.get_widget("treeview_restore_errors_conf").append_column(column)


        # i18n - Page 0 (choose backup or restore)
        self.wTree.get_widget("label_wizard1").set_markup("<big><b>" + _("Backup or Restore") + "</b></big>")
        self.wTree.get_widget("label_wizard2").set_markup("<i><span foreground=\"#555555\">" + _("Choose from the following options") + "</span></i>")

        self.wTree.get_widget("label_create_backup").set_text(_("Backup files"))
        self.wTree.get_widget("label_restore_backup").set_text(_("Restore files"))
        self.wTree.get_widget("label_create_packages").set_text(_("Backup software selection"))
        self.wTree.get_widget("label_restore_packages").set_text(_("Restore software selection"))
        self.wTree.get_widget("label_create_backup_timer").set_text(_("Backup or Remove regularly"))
        self.wTree.get_widget("label_backup_restore_conf").set_text(_("Backup or restore your configure"))
        self.wTree.get_widget("label_create_backup1").set_text(_("Create a new backup of your system"))
        self.wTree.get_widget("label_restore_backup1").set_text(_("restore a backup you have created system"))

        self.wTree.get_widget("label_detail1").set_markup("<small>" + _("Make a backup of your files") + "</small>")
        self.wTree.get_widget("label_detail2").set_markup("<small>" + _("Save the list of installed applications") + "</small>")
        self.wTree.get_widget("label_detail3").set_markup("<small>" + _("Restore a previous backup") + "</small>")
        self.wTree.get_widget("label_detail4").set_markup("<small>" + _("Restore previously installed applications") + "</small>")
        self.wTree.get_widget("label_detail5").set_markup("<small>" + _("Backup files or Remove systembackup regularly with the timer") + "</small>")
        self.wTree.get_widget("label_detail6").set_markup("<small>" + _("Backup or restore your configure for you") + "</small>")
        self.wTree.get_widget("label_detail7").set_markup("<small>" + _("Backup your system for you") + "</small>")
        self.wTree.get_widget("label_detail8").set_markup("<small>" + _("Backup or restore your system for you") + "</small>")

        self.wTree.get_widget("image_backup_data").set_from_file("/usr/lib/nfsbackup/backup-data.svg")
        self.wTree.get_widget("image_restore_data").set_from_file("/usr/lib/nfsbackup/restore-data.svg")
        self.wTree.get_widget("image_backup_software").set_from_file("/usr/lib/nfsbackup/backup-software.svg")
        self.wTree.get_widget("image_restore_software").set_from_file("/usr/lib/nfsbackup/restore-software.svg")
        self.wTree.get_widget("image_backup_timer").set_from_file("/usr/lib/nfsbackup/backup-timer.svg")
        self.wTree.get_widget("image_backup_restore_conf").set_from_file("/usr/lib/nfsbackup/configure.svg")
        self.wTree.get_widget("image_backup_data1").set_from_file("/usr/lib/nfsbackup/backup-data.svg")
        self.wTree.get_widget("image_restore_data1").set_from_file("/usr/lib/nfsbackup/restore-data.svg")

        # i18n - Page 1 (choose backup directories)
        self.wTree.get_widget("label_title_destination").set_markup("<big><b>" + _("Backup files") + "</b></big>")
        self.wTree.get_widget("label_caption_destination").set_markup("<i><span foreground=\"#555555\">" + _("Please select a source and a destination for your backup") + "</span></i>")

        self.wTree.get_widget("label_addfile").set_label(_("Add files"))
        self.wTree.get_widget("label_addfolder").set_label(_("Add folder"))
        self.wTree.get_widget("label_remov").set_label(_("Remove"))

        self.wTree.get_widget("label_backup_dest").set_label(_("Backup destination:"))
        self.wTree.get_widget("label_expander").set_label(_("Advanced options"))
        self.wTree.get_widget("label_backup_desc").set_label(_("Description:"))
        self.wTree.get_widget("label_compress").set_label(_("Output:"))
        self.wTree.get_widget("label_overwrite_dest").set_label(_("Overwrite:"))
        self.wTree.get_widget("checkbutton_integrity").set_label(_("Confirm integrity"))
        self.wTree.get_widget("checkbutton_links").set_label(_("Follow symlinks"))
        self.wTree.get_widget("checkbutton_perms").set_label(_("Preserve permissions"))
        self.wTree.get_widget("checkbutton_times").set_label(_("Preserve timestamps"))

        # i18n - Page 2 (backup timer main window)
        self.wTree.get_widget("label_title_timer").set_markup("<big><b>" + _("Backup-timer setup") + "</b></big>")
        self.wTree.get_widget("label_caption_timer").set_markup("<i><span foreground=\"#555555\">" + _("The list below shows the backup-timers you added") + "</span></i>")
        self.wTree.get_widget("label_create_timer").set_label(_("Create an backup-timer"))
        self.wTree.get_widget("label_delete_timer").set_label(_("Delete an backup-timer"))
        self.wTree.get_widget("label_remove_system").set_label(_("remove old systembackup"))

        # i18n - Page 3 (backup overview)
        self.wTree.get_widget("label_title_review").set_markup("<big><b>" + _("Backup files") + "</b></big>")
        self.wTree.get_widget("label_caption_review").set_markup("<i><span foreground=\"#555555\">" + _("Please review the information below before starting the backup") + "</span></i>")

		        # i18n - Page 4 (backing up status)
        self.wTree.get_widget("label_title_copying").set_markup("<big><b>" + _("Backup files") + "</b></big>")
        self.wTree.get_widget("label_caption_copying").set_markup("<i><span foreground=\"#555555\">" + _("Please wait while your files are being backed up") + "</span></i>")
        self.wTree.get_widget("label_current_file").set_label(_("Backing up:"))
	
		#######################################################################################################
		# i18n -Page 27 (backing up system status)
        self.wTree.get_widget("label_title_copying2").set_markup("<big><b>" + _("Backup your system") + "</b></big>")
        self.wTree.get_widget("label_caption_copying2").set_markup("<i><span foreground=\"#555555\">" + _("Please wait while your system are being backed up") + "</span></i>")
        self.wTree.get_widget("label_current_file2").set_label(_("Backing up:"))

		# i18n - Page 30 (restore system status)
        self.wTree.get_widget("label_title_copying3").set_markup("<big><b>" + _("Restore system") + "</b></big>")
        self.wTree.get_widget("label_caption_copying").set_markup("<i><span foreground=\"#555555\">" + _("Please wait while your system are being restored") + "</span></i>")
        self.wTree.get_widget("label_current_file3").set_label(_("Restoring:"))

		#########################################################################################################


        # i18n - Page 5 (backup complete)
        self.wTree.get_widget("label_title_finished").set_markup("<big><b>" + _("Backup files") + "</b></big>")
        self.wTree.get_widget("label_caption_finished").set_markup("<i><span foreground=\"#555555\">" + _("The backup is now finished") + "</span></i>")

        # i18n -Page 28 (system backup complete)
        self.wTree.get_widget("label_title_finished2").set_markup("<big><b>" + _("Backup your system") + "</b></big>")
        self.wTree.get_widget("label_caption_finished2").set_markup("<i><span foreground=\"#555555\">" + _("The system backup is now finished") + "</span></i>")


        # i18n - Page 6 (Restore locations)
        self.wTree.get_widget("label_title_restore1").set_markup("<big><b>" + _("Restore files") + "</b></big>")
        self.wTree.get_widget("label_caption_restore1").set_markup("<i><span foreground=\"#555555\">" + _("Please choose the type of backup to restore, its location and a destination") + "</span></i>")
        self.wTree.get_widget("radiobutton_archive").set_label(_("Archive"))
        self.wTree.get_widget("radiobutton_dir").set_label(_("Directory"))
        self.wTree.get_widget("label_addfile2").set_label(_("Add files"))
        self.wTree.get_widget("label_addfolder2").set_label(_("Add folder"))
        self.wTree.get_widget("label_remov2").set_label(_("Remove"))
        self.wTree.get_widget("label_restore_advanced").set_label(_("Advanced options"))
        self.wTree.get_widget("label_restore_overwrite").set_label(_("Overwrite:"))

        # i18n - Page 7 (Restore overview)
        self.wTree.get_widget("label_title_restore2").set_markup("<big><b>" + _("Restore files") + "</b></big>")
        self.wTree.get_widget("label_caption_restore2").set_markup("<i><span foreground=\"#555555\">" + _("Please review the information below") + "</span></i>")
        self.wTree.get_widget("label_overview_source").set_markup("<b>" + _("Source:") + "</b>")
        self.wTree.get_widget("label_overview_description").set_markup("<b>" + _("Description:") + "</b>")

#######################################################################################################
		# i18n - Page 26 (backup overview1)
        self.wTree.get_widget("label_title_backup_syste10").set_markup("<big><b>" + _("Backup system") + "</b></big>")
        self.wTree.get_widget("label_caption_backup10").set_markup("<i><span foreground=\"#555555\">" + _("Please review the information below before starting the system backup") + "</span></i>")
        self.wTree.get_widget("label_overview_source1").set_markup("<b>" + _("Source:") + "</b>")
        self.wTree.get_widget("label_overview_description1").set_markup("<b>" + _("Description:") + "</b>")

        self.wTree.get_widget("label_overview_dest1").set_markup("<b>" + _("Backup system destination:") + "</b>")
		##################################################################################################

        # i18n - Page 8 (restore status)
        self.wTree.get_widget("label_title_restore3").set_markup("<big><b>" + _("Restore files") + "</b></big>")
        self.wTree.get_widget("label_caption_restore3").set_markup("<i><span foreground=\"#555555\">" + _("Please wait while your files are being restored") + "</span></i>")
        self.wTree.get_widget("label_restore_status").set_label(_("Restoring:"))

        # i18n - Page 9 (restore complete)
        self.wTree.get_widget("label_overview_dest").set_markup("<b>" + _("Restore destination:") + "</b>")
        self.wTree.get_widget("label_title_restore4").set_markup("<big><b>" + _("Restore files") + "</b></big>")
        self.wTree.get_widget("label_caption_restore4").set_markup("<i><span foreground=\"#555555\">" + _("The restoration of the files is now finished") + "</span></i>")

        # i18n - Page 10 (packages)
        self.wTree.get_widget("label_title_software_backup1").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
        self.wTree.get_widget("label_caption_software_backup1").set_markup("<i><span foreground=\"#555555\">" + _("Please choose a destination") + "</span></i>")

		# i18n - Page 25 (system_backup)
		###############################################################################################################################
	
        self.wTree.get_widget("label_title_backup_system").set_markup("<big><b>" + _("Backup your system") + "</b></big>")
        self.wTree.get_widget("label_caption_backup_system").set_markup("<i><span foreground=\"#555555\">" + _("Please choose a destination") + "</span></i>")
       
		###############################################################################################################################

        # i18n - Page 11 (package list)
        self.wTree.get_widget("label_title_software_backup2").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
        self.wTree.get_widget("label_caption_software_backup2").set_markup("<i><span foreground=\"#555555\">" + _("The list below shows the packages you added to Linux Mint") + "</span></i>")
        self.wTree.get_widget("label_select").set_label(_("Select all"))
        self.wTree.get_widget("label_deselect").set_label(_("Deselect all"))

        # i18n - Page 12 (backing up packages)
        self.wTree.get_widget("label_title_software_backup3").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
        self.wTree.get_widget("label_caption_software_backup3").set_markup("<i><span foreground=\"#555555\">" + _("Please wait while your software selection is being backed up") + "</span></i>")
        self.wTree.get_widget("label_current_package").set_label(_("Backing up:"))

        # i18n - Page 13 (packages done)
        self.wTree.get_widget("label_title_software_backup4").set_markup("<big><b>" + _("Backup software selection") + "</b></big>")
        self.wTree.get_widget("label_caption_software_backup4").set_markup("<i><span foreground=\"#555555\">" + _("The backup is now finished") + "</span></i>")

        # i18n - Page 14 (package restore)
        self.wTree.get_widget("label_title_software_restore1").set_markup("<big><b>" + _("Restore software selection") + "</b></big>")
        self.wTree.get_widget("label_caption_software_restore1").set_markup("<i><span foreground=\"#555555\">" + _("Please select a saved software selection") + "</span></i>")
        self.wTree.get_widget("label_package_source").set_markup(_("Software selection:"))

		# i18n - Page 29 (system restore select destination)
        self.wTree.get_widget("label_title_software_restore8").set_markup("<big><b>" + _("Restore system selection") + "</b></big>")
        self.wTree.get_widget("label_caption_software_restore8").set_markup("<i><span foreground=\"#555555\">" + _("Please select a saved system selection") + "</span></i>")
        self.wTree.get_widget("label_package_source5").set_markup(_("System selection:"))



        # i18n - Page 15 (packages list)
        self.wTree.get_widget("label_title_software_restore2").set_markup("<big><b>" + _("Restore software selection") + "</b></big>")
        self.wTree.get_widget("label_caption_software_restore2").set_markup("<i><span foreground=\"#555555\">" + _("Select the packages you want to install") + "</span></i>")
        self.wTree.get_widget("label_select_list").set_label(_("Select all"))
        self.wTree.get_widget("label_deselect_list").set_label(_("Deselect all"))
        self.wTree.get_widget("label_refresh").set_label(_("Refresh"))

        # i18n - Page 16 (packages install done)
        self.wTree.get_widget("label_title_software_restore3").set_markup("<big><b>" + _("Restore software selection") + "</b></big>")
        self.wTree.get_widget("label_caption_software_restore3").set_markup("<i><span foreground=\"#555555\">" + _("The restoration is now finished") + "</span></i>")
        self.wTree.get_widget("label_install_done_value").set_markup(_("Your package selection was restored succesfully"))

        # i18n - Page 17 (choose backup directories)
        self.wTree.get_widget("label_title_destination1").set_markup("<big><b>" + _("Backup-timer setup") + "</b></big>")
        self.wTree.get_widget("label_caption_destination1").set_markup("<i><span foreground=\"#555555\">" + _("Please select a source and a destination for your backup") + "</span></i>")

        self.wTree.get_widget("label_addfile1").set_label(_("Add files"))
        self.wTree.get_widget("label_addfolder1").set_label(_("Add folder"))
        self.wTree.get_widget("label_remov1").set_label(_("Remove"))

        self.wTree.get_widget("label_backup_dest1").set_label(_("Backup destination:"))
        self.wTree.get_widget("label_expander1").set_label(_("Advanced options"))
        self.wTree.get_widget("label_compress1").set_label(_("Output:"))

        # i18n - Page 18 (choose backup time)
        self.wTree.get_widget("label_title_destination2").set_markup("<big><b>" + _("Backup-timer setup") + "</b></big>")
        self.wTree.get_widget("label_caption_destination2").set_markup("<i><span foreground=\"#555555\">" + _("Please select strategy and time for your backup") + "</span></i>")

        self.wTree.get_widget("radiobutton_onetime").set_label(_("One time"))
        self.wTree.get_widget("radiobutton_periodic").set_label(_("weekly"))
        self.wTree.get_widget("radiobutton_month").set_label(_("monthly"))

        self.wTree.get_widget("label_time").set_label(_("time"))
        self.wTree.get_widget("label_hour").set_label(_("hour"))
        self.wTree.get_widget("label_minute").set_label(_("minute"))

        self.wTree.get_widget("label_month").set_label(_("month"))
        self.wTree.get_widget("label_day").set_label(_("day"))
        self.wTree.get_widget("label_day1").set_label(_("day"))
        self.wTree.get_widget("checkbutton_Mon").set_label(_("Monday"))
        self.wTree.get_widget("checkbutton_Tue").set_label(_("Tuesday"))
        self.wTree.get_widget("checkbutton_Wed").set_label(_("Wednesday"))
        self.wTree.get_widget("checkbutton_Thu").set_label(_("Thursday"))
        self.wTree.get_widget("checkbutton_Fri").set_label(_("Friday"))
        self.wTree.get_widget("checkbutton_Sat").set_label(_("Saturday"))
        self.wTree.get_widget("checkbutton_Sun").set_label(_("Sunday"))

        # i18n - Page 19 (choose backup or restore conf)
        self.wTree.get_widget("label_title_conf").set_markup("<big><b>" + _("Backup or restore your configure") + "</b></big>")
        self.wTree.get_widget("label_caption_conf").set_markup("<i><span foreground=\"#555555\">" + _("Please follow the tip and make your operation") + "</span></i>")

        self.wTree.get_widget("label_conf").set_label(_("Please select configure for your backup or recovery"))

        # i18n - Page 20 (backup or restore configure overview)
        self.wTree.get_widget("label_title_review_conf").set_markup("<big><b>" + _("Backup configure files") + "</b></big>")
        self.wTree.get_widget("label_caption_review_conf").set_markup("<i><span foreground=\"#555555\">" + _("Please review the information below before starting the backup") + "</span></i>")

        # i18n - Page 21 (backing up configure status)
        self.wTree.get_widget("label_title_copying_conf").set_markup("<big><b>" + _("Backup configure files") + "</b></big>")
        self.wTree.get_widget("label_caption_copying_conf").set_markup("<i><span foreground=\"#555555\">" + _("Please wait while your files are being backed up") + "</span></i>")
        self.wTree.get_widget("label_current_file_conf").set_label(_("Backing up:"))

        # i18n - Page 22 (backup configure completed)
        self.wTree.get_widget("label_title_finished_conf").set_markup("<big><b>" + _("Backup configure files") + "</b></big>")
        self.wTree.get_widget("label_caption_finished_conf").set_markup("<i><span foreground=\"#555555\">" + _("The backup is now finished") + "</span></i>")

        # i18n - Page 23 (restoring configure status)
        self.wTree.get_widget("label_title_restore_conf").set_markup("<big><b>" + _("Restore configure files") + "</b></big>")
        self.wTree.get_widget("label_caption_restore_conf").set_markup("<i><span foreground=\"#555555\">" + _("Please wait while your files are being restored") + "</span></i>")
        self.wTree.get_widget("label_restore_current_conf").set_label(_("Restoring:"))

        # i18n - Page 24 (restore configure completed)
        self.wTree.get_widget("label_title_restore_finished_conf").set_markup("<big><b>" + _("Restore configure files") + "</b></big>")
        self.wTree.get_widget("label_caption_restore_finished_conf").set_markup("<i><span foreground=\"#555555\">" + _("The restoration of the files is now finished") + "</span></i>")

    ''' show the pretty aboutbox. '''
    def about_callback(self, w):
        dlg = gtk.AboutDialog()
        dlg.set_title(_("About"))
        dlg.set_program_name(_("Backup Tool"))
        try:
            h = open('/usr/share/common-licenses/GPL','r')
            s = h.readlines()
            gpl = ""
            for line in s:
                gpl += line
            h.close()
            dlg.set_license(gpl)
        except Exception, detail:
            print detail
        try:
            version = commands.getoutput("/usr/lib/nfsbackup/version.py nfsbackup")
            dlg.set_version(version)
        except Exception, detail:
            print detail

        dlg.set_authors(["Nfschina <os_support@nfschina.com>"])
        dlg.set_icon_from_file("/usr/lib/nfsbackup/icon.png")
        dlg.set_logo(gtk.gdk.pixbuf_new_from_file("/usr/lib/nfsbackup/icon.svg"))
        def close(w, res):
            if res == gtk.RESPONSE_CANCEL:
                w.hide()
        dlg.connect("response", close)
        dlg.show()

    '''callback for combobox_conf'''
    def com_conf_callback(self,widget):
        self.conf_type = widget.get_active()
        #if self.conf_type is not backup
        if self.conf_type > 2:
            self.wTree.get_widget("button_dest_conf").set_sensitive(False)
            self.wTree.get_widget("button_sour_conf").set_sensitive(True)
        else:
            self.wTree.get_widget("button_dest_conf").set_sensitive(True)
            self.wTree.get_widget("button_sour_conf").set_sensitive(False)
        self.conf_dest = ""
        self.wTree.get_widget("entry_dest_conf").set_text(self.conf_dest)
        self.wTree.get_widget("entry_sour_conf").set_text(self.conf_dest)

    def back_main_callback(self,widget):
        book = self.wTree.get_widget("notebook1")
        sel = book.get_current_page()
        if(sel == 30 or (sel == 27 and self.system_backup_stat == True)):
            file_message = _("Back to the home page will end the current task, determinate to do so?")
            dialog = gtk.MessageDialog(None, 0,  gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, _("Back to the home page?"))
            dialog.format_secondary_text(file_message)
            response = dialog.run()
            if(response == gtk.RESPONSE_YES):
                self.operating = False
                dialog.destroy()
            elif(response == gtk.RESPONSE_NO):
                dialog.destroy()
                return 

        self.wTree.get_widget("notebook1").set_current_page(0)
        self.wTree.get_widget("button_back").set_sensitive(False)
        self.wTree.get_widget("button_back").hide()
        self.wTree.get_widget("button_forward").hide()
        self.wTree.get_widget("button_about").show()
        self.wTree.get_widget("button_back_main").hide()
        self.wTree.get_widget("button_back_main").set_sensitive(False)
        self.wTree.get_widget("button_apply").hide()
        self.wTree.get_widget("button_apply").set_sensitive(False)


    def abt_resp(self, w, r):
        if r == gtk.RESPONSE_CANCEL:
            w.hide()
    '''
    def save_backup_source(self, w):
        self.backup_source = w.get_filename()
    def save_backup_dest(self, w):
        self.backup_dest = w.get_filename()
    '''
    ''' set entry1 and entry2 ....'''
    def set_entry1(self,widget):
        dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        dialog.set_current_folder("/")
        dialog.set_select_multiple(False)
        if dialog.run() == gtk.RESPONSE_OK:
            book = self.wTree.get_widget("notebook1")
            sel = book.get_current_page()
            if(sel == 1):
                self.wTree.get_widget("entry1").set_text(dialog.get_filename())
                self.backup_dest = self.wTree.get_widget("entry1").get_text()
            elif(sel == 17):
                self.wTree.get_widget("entry5").set_text(dialog.get_filename())
                self.backup_timer_dest = self.wTree.get_widget("entry5").get_text()
            elif(sel == 19):
                self.wTree.get_widget("entry_dest_conf").set_text(dialog.get_filename())
                self.conf_dest = self.wTree.get_widget("entry_dest_conf").get_text()
        dialog.destroy()

    def set_entry_sour(self,widget):
        dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_OPEN, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        dialog.set_current_folder("/")
        dialog.set_select_multiple(False)
        if dialog.run() == gtk.RESPONSE_OK:
            self.wTree.get_widget("entry_sour_conf").set_text(dialog.get_filename())
            self.conf_dest = self.wTree.get_widget("entry_sour_conf").get_text()
        dialog.destroy()

    def set_entry2(self,widget):
        if(self.restore_archive == True):
            dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_OPEN, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        else:
            dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        dialog.set_current_folder("/")
        dialog.set_select_multiple(False)
        if dialog.run() == gtk.RESPONSE_OK:
            self.wTree.get_widget("entry2").set_text(dialog.get_filename())
        dialog.destroy()

    def set_entry3(self,widget):
        dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        dialog.set_current_folder("/")
        dialog.set_select_multiple(False)
        if dialog.run() == gtk.RESPONSE_OK:
            self.wTree.get_widget("entry3").set_text(dialog.get_filename())
        dialog.destroy()

    def set_entry4(self,widget):
        dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        dialog.set_current_folder("/")
        dialog.set_select_multiple(False)
        if dialog.run() == gtk.RESPONSE_OK:
            self.wTree.get_widget("entry4").set_text(dialog.get_filename())
        dialog.destroy()

############################################################################

	
    def set_entry6(self,widget):
        dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        dialog.set_current_folder("/")
        dialog.set_select_multiple(False)
        if dialog.run() == gtk.RESPONSE_OK:
            self.wTree.get_widget("entry6").set_text(dialog.get_filename())
        dialog.destroy()

############################################################################

    ''' handle the file-set signal '''
    def check_reset_file(self, w):
        #fileset = w.get_filename()
        #if(fileset not in self.backup_source):
        if(self.tar is not None):
            self.tar.close()
            self.tar = None
        #self.backup_source = fileset

    ''' switch between archive and directory sources '''
    def archive_switch(self, w):
        if(self.wTree.get_widget("radiobutton_archive").get_active()):
            # dealing with archives
            self.restore_archive = True
            self.wTree.get_widget("button_addfile_restore").set_sensitive(False)
            self.wTree.get_widget("button_addfolder_restore").set_sensitive(False)
            self.wTree.get_widget("button_remove_restore").set_sensitive(False)
            self.wTree.get_widget("button_restore_sour").set_sensitive(True)
        else:
            self.restore_archive = False
            self.wTree.get_widget("button_addfile_restore").set_sensitive(True)
            self.wTree.get_widget("button_addfolder_restore").set_sensitive(True)
            self.wTree.get_widget("button_remove_restore").set_sensitive(True)
            self.wTree.get_widget("button_restore_sour").set_sensitive(False)
       
    def select_periodic(self, w):
       
        if(self.wTree.get_widget("radiobutton_onetime").get_active()):
            self.set_periodic= False
            self.month_periodic = False
           
            self.wTree.get_widget("combobox_month").set_sensitive(True)
            self.wTree.get_widget("combobox_day").set_sensitive(True)
            self.wTree.get_widget("combobox_day1").set_sensitive(False)
     
            self.wTree.get_widget("checkbutton_Mon").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Tue").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Wed").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Thu").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Fri").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Sat").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Sun").set_sensitive(False)
           
        elif(self.wTree.get_widget("radiobutton_periodic").get_active()):
            self.set_periodic= True
            self.month_periodic = False
            self.wTree.get_widget("combobox_month").set_sensitive(False)
            self.wTree.get_widget("combobox_day").set_sensitive(False)
            self.wTree.get_widget("combobox_day1").set_sensitive(False)

            self.wTree.get_widget("checkbutton_Mon").set_sensitive(True)
            self.wTree.get_widget("checkbutton_Tue").set_sensitive(True)
            self.wTree.get_widget("checkbutton_Wed").set_sensitive(True)
            self.wTree.get_widget("checkbutton_Thu").set_sensitive(True)
            self.wTree.get_widget("checkbutton_Fri").set_sensitive(True)
            self.wTree.get_widget("checkbutton_Sat").set_sensitive(True)
            self.wTree.get_widget("checkbutton_Sun").set_sensitive(True)
        else:
            self.month_periodic = True
            self.set_periodic= False
            self.wTree.get_widget("combobox_day1").set_sensitive(True)
            self.wTree.get_widget("checkbutton_Mon").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Tue").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Wed").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Thu").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Fri").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Sat").set_sensitive(False)
            self.wTree.get_widget("checkbutton_Sun").set_sensitive(False)
            self.wTree.get_widget("combobox_month").set_sensitive(False)
            self.wTree.get_widget("combobox_day").set_sensitive(False)

    ''' handler for checkboxes '''
    def handle_checkbox(self, widget):
        if(widget == self.wTree.get_widget("checkbutton_integrity")):
            self.postcheck = widget.get_active()
        elif(widget == self.wTree.get_widget("checkbutton_perms")):
            self.preserve_perms = widget.get_active()
        elif(widget == self.wTree.get_widget("checkbutton_times")):
            self.preserve_times = widget.get_active()
        elif(widget == self.wTree.get_widget("checkbutton_links")):
            self.follow_links = widget.get_active()

    ''' Add file '''
    def add_file(self, widget):
        book = self.wTree.get_widget("notebook1")
        sel = book.get_current_page()
        if(sel == 1):
            model = self.wTree.get_widget("treeview_source").get_model()
        elif(sel == 6):
            model = self.wTree.get_widget("treeview_source_restore").get_model()
        else:
            model = self.wTree.get_widget("treeview_source1").get_model()
        dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_OPEN, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        dialog.set_current_folder("/")
        dialog.set_select_multiple(True)
        if dialog.run() == gtk.RESPONSE_OK:
            filenames = dialog.get_filenames()
            for filename in filenames:
                model.append([filename[:], self.fileIcon, filename])
        dialog.destroy()

    ''' Add folder '''

    def add_folder(self, widget):
        book = self.wTree.get_widget("notebook1")
        sel = book.get_current_page()
        if(sel == 1):
            model = self.wTree.get_widget("treeview_source").get_model()
        elif(sel == 6):
            model = self.wTree.get_widget("treeview_source_restore").get_model()
        else:
            model = self.wTree.get_widget("treeview_source1").get_model()
        dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OPEN, gtk.RESPONSE_OK))
        dialog.set_current_folder("/")
        dialog.set_select_multiple(True)
        if dialog.run() == gtk.RESPONSE_OK:
            filenames = dialog.get_filenames()
            for filename in filenames:
                model.append([filename[:], self.dirIcon, filename])
        dialog.destroy()

    ''' Remove the exclude '''    
    def remove_exclude(self, widget):
        book = self.wTree.get_widget("notebook1")
        sel = book.get_current_page()
        if(sel == 1):
            model = self.wTree.get_widget("treeview_source").get_model()
            selection = self.wTree.get_widget("treeview_source").get_selection()
        elif(sel == 6):
            model = self.wTree.get_widget("treeview_source_restore").get_model()
            selection = self.wTree.get_widget("treeview_source_restore").get_selection()
        else:
            model = self.wTree.get_widget("treeview_source1").get_model()
            selection = self.wTree.get_widget("treeview_source1").get_selection()
        selected_rows = selection.get_selected_rows()[1]
        # don't you just hate python? :) Here's another hack for python not to get confused with its own paths while we're deleting multiple stuff.
        # actually.. gtk is probably to blame here.
        args = [(model.get_iter(path)) for path in selected_rows]
        for iter in args:
            model.remove(iter)

    ''' Cancel clicked '''
    def cancel_callback(self, widget):
        if(self.tar is not None):
            self.tar.close()
            self.tar = None
        if(self.system_backup_stat):
            self.wTree.get_widget("button_cancel").set_sensitive(False)

        if(self.operating):
            # in the middle of a job, let the appropriate thread
            # handle the cancel
            self.operating = False
        else:
            # just quit :)
            gtk.main_quit()

    def Messaged(self,message):
        messag = "<big>" + _("Are you sure to add the timer :") + "</big>\r\n"
        messag += message
        dialog = gtk.MessageDialog(None, 0, gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, messag)
        
        dialog.set_markup(messag)
        dialog.set_title(_("Backup Tool"))
        dialog.set_position(gtk.WIN_POS_CENTER)
        response = dialog.run()
        if response == gtk.RESPONSE_YES:
            flag = True
        else:
            flag = False
        dialog.destroy()
        return flag

    ''' First page buttons '''
    def wizard_buttons_cb(self, widget, param):
        self.wTree.get_widget("notebook1").set_current_page(param)
        self.wTree.get_widget("button_back_main").show()
        self.wTree.get_widget("button_back_main").set_sensitive(True)
        self.wTree.get_widget("button_back").show()
        self.wTree.get_widget("button_back").set_sensitive(True)
        if(param == 2):
            thr = threading.Thread(group=None, name="NFSBackup-packages", target=self.load_backup_timer, args=(), kwargs={})
            thr.start()
            self.wTree.get_widget("button_apply").show()
            self.wTree.get_widget("button_apply").set_sensitive(True)
        else:
            self.wTree.get_widget("button_forward").show()
        self.wTree.get_widget("button_about").hide()
        if(param == 14):
            self.wTree.get_widget("button_forward").set_sensitive(False)

		#####################################################################################
        elif(param == 29):
            if(self.system_restore_stat):
                self.wTree.get_widget("notebook1").set_current_page(30)
                self.wTree.get_widget("button_apply").hide()
                self.wTree.get_widget("button_back").hide()
                self.wTree.get_widget("button_forward").hide()
            elif(self.system_source is None):
            	self.wTree.get_widget("button_forward").set_sensitive(False)
            else:
            	self.wTree.get_widget("button_forward").set_sensitive(True)
		#######################################################################################
       
        elif(param != 2):
            self.wTree.get_widget("button_forward").set_sensitive(True)

    ''' Next button '''
    def forward_callback(self, widget):
        book = self.wTree.get_widget("notebook1")
        sel = book.get_current_page()
        self.wTree.get_widget("button_back").set_sensitive(True)
        self.wTree.get_widget("button_back_main").show()
        self.wTree.get_widget("button_back_main").set_sensitive(True)
        if(sel == 1):
            # choose source/dest
            sources = self.wTree.get_widget("treeview_source").get_model()
            if(not sources.get_iter_first()):
                MessageDialog(_("Backup Tool"), _("Please choose the source"), gtk.MESSAGE_WARNING).show()
                return
            if(not self.backup_dest):
                MessageDialog(_("Backup Tool"), _("Please choose the destination"), gtk.MESSAGE_WARNING).show()
                return
            for row in sources:
                if(not self.backup_dest.find(row[2])):
                    MessageDialog(_("Backup Tool"), _("The source includes the destination"), gtk.MESSAGE_WARNING).show()
                    return
            self.description = self.wTree.get_widget("entry_desc").get_text()
            # show overview
            model = gtk.ListStore(str, str)
            first_source_flag = True
            for row in sources:
                if(first_source_flag):
                    model.append(["<b>" + _("Source") + "</b>",row[2]])
                    first_source_flag=False
                else:
                    model.append(["<b>" + _("   ") + "</b>", row[2]])
            model.append(["<b>" + _("Backup destination:") + "</b>", self.backup_dest])
            if (self.description != ""):
                model.append(["<b>" + _("Description") + "</b>", self.description])
            # find compression format
            sel = self.wTree.get_widget("combobox_compress").get_active()
            comp = self.wTree.get_widget("combobox_compress").get_model()
            model.append(["<b>" + _("Compression") + "</b>", comp[sel][0]])
            # find overwrite rules
            sel = self.wTree.get_widget("combobox_delete_dest").get_active()
            over = self.wTree.get_widget("combobox_delete_dest").get_model()
            model.append(["<b>" + _("Overwrite destination files") + "</b>", over[sel][0]])

            self.wTree.get_widget("treeview_overview").set_model(model)
            book.set_current_page(3)
            self.wTree.get_widget("button_forward").hide()
            self.wTree.get_widget("button_apply").show()
            self.wTree.get_widget("button_apply").set_sensitive(True)
        elif(sel == 2):
         
            timers = self.wTree.get_widget("treeview_backup_timer").get_model()
            if(self.update_flag):
                try:
                    bl = open("/usr/lib/nfsbackup/cronfile", "w+")
                    bl.write("#cronfile\n")
                    
                except Exception, detail:
                    print detail
                for row in timers:
                    item = row[0].split('\n')
                   
                    time = item[-3].split(':')
                    source = item[0].split(':')
                    self.timer_command = ""
                    if(time[2] == "00"):
                        self.timer_command += '0' + time[1] + ' '
                    else:
                        self.timer_command += time[2].lstrip('0') + time[1] + ' '
                    strategy = item[-2].decode('utf-8').lstrip(_("Strategy")).rstrip(_("a time"))
                    
                    if strategy == _("every day"):
                        self.timer_command += '* * * '
                    elif strategy.find("every month") >= 0:
                        d= strategy.split(" ")
                        self.timer_command += d[2] + ' ' + '* *' + ' '
                    else:
                        strategy1 = strategy.strip(_("every"))
                        if strategy1.decode('utf-8').find(_("month")) >= 0:
                            m,d= strategy1.split(_("month"))
                            self.timer_command += d[:-1] + ' ' + m + ' ' + '*' + ' '
                        else:
                            self.timer_command += '* * '
                            week = strategy1.rstrip(' ').split(' ')
                            
                            for w in week:
                                if w.decode('utf-8') == _("one"):
                                    self.timer_command += '1,'
                                elif w.decode('utf-8') == _("two"):
                                    self.timer_command += '2,'
                                elif w.decode('utf-8') == _("three"):
                                    self.timer_command += '3,'
                                elif w.decode('utf-8') == _("four"):
                                    self.timer_command += '4,'
                                elif w.decode('utf-8') == _("five"):
                                    self.timer_command += '5,'
                                elif w.decode('utf-8') == _("six"):
                                    self.timer_command += '6,'
                                elif w.decode('utf-8') == _("seven"):
                                    self.timer_command += '0,'
                            self.timer_command = self.timer_command[:-1] + ' '
                    if source[1].find("NFS") > -1 :
                        self.timer_command += '/usr/lib/nfsbackup/systembackup.py '
                        self.timer_command += self.backup_timer_dest + '\n'
                    elif source[1].find("remove") > -1:
                        self.timer_command += '/usr/lib/nfsbackup/remove_timer.py '
                        self.timer_command += self.backup_timer_dest + '\n'
                    else:
                        if(item[-1].split(': ')[1].decode('utf-8') == _("Preserve structure always overwrite")):
                            self.timer_command += '/usr/lib/nfsbackup/dir.py '
                        else:
                            self.timer_command += '/usr/lib/nfsbackup/tar.py '
                        for i in item[0:-4]:
                            if i == item[0]:
                                self.timer_command += i.split(': ')[1] + ' '
                            else:
                                self.timer_command += i.strip(' ') + ' '
                        self.timer_command += item[-4].split(': ')[1] + '\n'
                    try:
                        bl.write(self.timer_command)
                    except Exception, detail:
                        print detail
                try:
                    bl.close()
                except Exception, detail:
                    print detail
                try:
                    os.system("service cron rstart")
                    os.system("crontab /usr/lib/nfsbackup/cronfile")
                except Exception, detail:
                    print detail
            else:
                MessageDialog(_("Backup Tool"), _("There no change to backup_timer"), gtk.MESSAGE_INFO).show()
                return
            self.wTree.get_widget("notebook1").set_current_page(0)
            self.wTree.get_widget("button_back").set_sensitive(False)
            self.wTree.get_widget("button_back").hide()
            self.wTree.get_widget("button_about").show()
            self.wTree.get_widget("button_back_main").hide()
            self.wTree.get_widget("button_back_main").set_sensitive(False)
            self.wTree.get_widget("button_apply").hide()
            self.wTree.get_widget("button_apply").set_sensitive(False)
        elif(sel == 3):
            # start copying :D
            book.set_current_page(4)
            self.wTree.get_widget("button_apply").set_sensitive(False)
            self.wTree.get_widget("button_back").set_sensitive(False)
            self.wTree.get_widget("button_back_main").hide()
            self.operating = True
            thread = threading.Thread(group=None, target=self.backup, name="NFSBackup-copy", args=(), kwargs={})
            thread.start()

        elif(sel == 4):
            # show info page.
            self.wTree.get_widget("button_forward").hide()
            self.wTree.get_widget("button_back").hide()
            book.set_current_page(5)

        elif(sel == 30):
			#show bar
            self.wTree.get_widget("button_forward").hide()
            self.wTree.get_widget("button_back").hide()
            book.set_current_page(5)

        elif(sel == 27):
            # show info page.
            self.wTree.get_widget("button_forward").hide()
            self.wTree.get_widget("button_back").hide()
            book.set_current_page(28)

        elif(sel == 6):
            # sanity check the files (file --mimetype)
            if(self.restore_archive == True):
                self.restore_source = self.wTree.get_widget("entry2").get_text()
                if(not self.restore_source or self.restore_source == ""):
                    MessageDialog(_("Backup Tool"), _("Please choose a file to restore from"), gtk.MESSAGE_WARNING).show()
                    return
            else:
                sources = self.wTree.get_widget("treeview_source_restore").get_model()
                if(not sources.get_iter_first()):
                    MessageDialog(_("Backup Tool"), _("Please choose a file to restore from"), gtk.MESSAGE_WARNING).show()
                    return
            self.restore_dest = self.wTree.get_widget("entry3").get_text()
            if(not self.restore_dest or self.restore_dest == ""):
                MessageDialog(_("Backup Tool"), _("Please choose a file to restore to"), gtk.MESSAGE_WARNING).show()
                return
            nfsfile = None
            self.tar = None
            try:
                if(self.restore_archive == True):
                    self.tar = tarfile.open(self.restore_source, "r")
                    nfsfile = self.tar.getmember(".nfsbackup")
                    self.tar = None
            except Exception, detail:
                if(nfsfile is None):
                    MessageDialog(_("Backup Tool"), _("This is not nfsbackup file."), gtk.MESSAGE_ERROR).show()
                    return
            thread = threading.Thread(group=None, target=self.prepare_restore, name="NFSBackup-prepare", args=(), kwargs={})
            thread.start()
        elif(sel == 7):
            # start restoring :D
            self.wTree.get_widget("button_apply").hide()
            self.wTree.get_widget("button_back").hide()
            self.wTree.get_widget("button_back_main").hide()
            book.set_current_page(8)
            self.operating = True
            thread = threading.Thread(group=None, target=self.restore, name="NFSBackup-restore", args=(), kwargs={})
            thread.start()

		###############################################################################
        elif(sel == 26):
            # start copying :D
            self.wTree.get_widget("button_back_main").show()
            self.wTree.get_widget("button_apply").hide()
            self.wTree.get_widget("button_back").hide()
            book.set_current_page(27)
            self.operating = True
            thread = threading.Thread(group=None, target=self.backup_system, name="NFSBackup-copy", args=(), kwargs={})
            thread.start()

		###################################################################################

        elif(sel == 8):
            # show last page(restore finished status)
            self.wTree.get_widget("button_forward").hide()
            self.wTree.get_widget("button_back").hide()
            book.set_current_page(9)
        elif(sel == 10):
            f = self.wTree.get_widget("entry4").get_text()
            if f is None or f == "":
                MessageDialog(_("Backup Tool"), _("Please choose a destination directory"), gtk.MESSAGE_ERROR).show()
                return
            else:
                self.package_dest = f
                self.operating = True
                book.set_current_page(11)
            thr = threading.Thread(group=None, name="NFSBackup-packages", target=self.load_packages, args=(), kwargs={})
            thr.start()
            self.wTree.get_widget("button_forward").hide()
            self.wTree.get_widget("button_apply").show()
            self.wTree.get_widget("button_apply").set_sensitive(True)

		####################################################################################
        elif(sel == 25):
            f = self.wTree.get_widget("entry6").get_text()
            n = open("/etc/os-release", "r")
            goal_name = '^PRETTY_NAME'
            for eachline in n:
                name_line = eachline
                value = re.search(goal_name, name_line, flags=0)
                if value is not None:
                    system_name = name_line[13:-2]
                    break
            n.close()

            self.wTree.get_widget("label_overview_source_value1").set_label(system_name)
            self.wTree.get_widget("label_overview_dest_value1").set_label(f)
            self.wTree.get_widget("label_overview_description_value1").set_label(_("Backup your system"))
            if f is None or f == "":
                MessageDialog(_("Backup Tool"), _("Please choose a destination directory"), gtk.MESSAGE_ERROR).show()
                return
            else:
                self.system_dest = f
                self.operating = True
                book.set_current_page(26)
	
            self.wTree.get_widget("button_forward").hide()
            self.wTree.get_widget("button_apply").show()
            self.wTree.get_widget("button_apply").set_sensitive(True)
            self.wTree.get_widget("progressbar3").hide()
            self.wTree.get_widget("label_caption_copying2").hide()
           
		###################################################################################
        elif(sel == 11):
            # show progress of packages page
            self.wTree.get_widget("button_forward").set_sensitive(False)
            self.wTree.get_widget("button_back").set_sensitive(False)
            book.set_current_page(12)
            '''
            f = self.wTree.get_widget("filechooserbutton_package_dest").get_filename()
            if f is None or f == "":
                MessageDialog(_("Backup Tool"), _("Please choose a destination directory"), gtk.MESSAGE_ERROR).show()
                return
            else:
            self.package_dest = f
            self.operating = True
            '''
            thr = threading.Thread(group=None, name="NFSBackup-packages", target=self.backup_packages, args=(), kwargs={})
            thr.start()
        elif(sel == 14):
            thr = threading.Thread(group=None, name="NFSBackup-packages", target=self.load_package_list, args=(), kwargs={})
            thr.start()
	    #######################################################################
        elif(sel == 29):
            if(not self.system_source or self.system_dest_dir == ""):
            	MessageDialog(_("Backup Tool"), _("Please choose the source file"), gtk.MESSAGE_WARNING).show()
                return
            #用户确认对话框
            file_message = _("Click yes to use the file \'%s\' for reduction." % (self.system_source))
            dialog = gtk.MessageDialog(None, 0,  gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, _("Begin to restore?"))
            dialog.format_secondary_text(file_message)
            response = dialog.run()
            if(response == gtk.RESPONSE_YES):
                self.wTree.get_widget("button_apply").hide()
                self.wTree.get_widget("button_back").hide()
                self.wTree.get_widget("button_forward").hide()
                self.wTree.get_widget("progressbar4").hide()
                #self.wTree.get_widget("label_caption_copying3").hide()
                book.set_current_page(30)

                #create a thread to restore system
                thread = threading.Thread(group=None, target=self.restore_system, name="NFSBackup-restore", args=(), kwargs={})
                thread.start()
            elif(response == gtk.RESPONSE_NO):
            	pass
            dialog.destroy()
	#######################################################################
        elif(sel == 15):
            inst = False
            model = self.wTree.get_widget("treeview_package_list").get_model()
            if(len(model) == 0):
                MessageDialog(_("Backup Tool"), _("No packages need to be installed at this time"), gtk.MESSAGE_INFO).show()
                return
            for row in model:
                if(row[0]):
                    inst = True
                    break
            if(not inst):
                MessageDialog(_("Backup Tool"), _("Please select one or more packages to install"), gtk.MESSAGE_ERROR).show()
                return
            else:
                thr = threading.Thread(group=None, name="NFSBackup-packages", target=self.install_packages, args=(), kwargs={})
                thr.start()
        elif(sel == 17):
            # show last page(timer setup)
            if self.systembackup_timer == False and self.remove_systembackup == False:
                sources = self.wTree.get_widget("treeview_source1").get_model()
                if(not sources.get_iter_first()):
                    MessageDialog(_("Backup Tool"), _("Please choose the source"), gtk.MESSAGE_WARNING).show()
                    return
                if(not self.backup_timer_dest):
                    MessageDialog(_("Backup Tool"), _("Please choose the destination"), gtk.MESSAGE_WARNING).show()
                    return
            book.set_current_page(18)
            self.wTree.get_widget("button_apply").show()
            self.wTree.get_widget("button_apply").set_sensitive(True)
            self.wTree.get_widget("button_forward").hide()
        elif(sel == 18):
            now = localtime()
            #for debug now = (2011, 3, 8)
            select_hour = self.wTree.get_widget("combobox_hour").get_active()
            select_minute = self.wTree.get_widget("combobox_minute").get_active()
            if self.remove_systembackup == True:
                Source = _("remove task : ")
            else:
                Source = _("Backup-timer source")
            sources = self.wTree.get_widget("treeview_source1").get_model()
            first_sources_flag = True
 
            if self.remove_systembackup == True:
                Source += "remove old Oerating Systembackup\n"
            else: 
                for row in sources:
                    if(first_sources_flag):
                        Source += row[2] + "\n"
                        first_sources_flag = False
                    else:
                        Source += "               " + row[2] + "\n"
            if self.remove_systembackup == True:
                Source +=_("System Backup path : ") + self.backup_timer_dest
            else:
                Source +=_("Backup-timer destination") + self.backup_timer_dest
            
            Source += "\n" + _("Time") + str(select_hour) + ":"
            if(select_minute < 10):
                Source += '0' + str(select_minute) + "\n" + _("Strategy")
            else:
                Source += str(select_minute) + "\n" + _("Strategy")
            if(self.set_periodic == False and self.month_periodic == False):
                select_month = self.wTree.get_widget("combobox_month").get_active() + 1
                select_day = self.wTree.get_widget("combobox_day").get_active() + 1
                month_leap = [4, 6, 9, 11]
                #filter invalid date
                if(select_month == 2 and (select_day == 30 or select_day == 31)):
                    MessageDialog(_("Backup Tool"), _("There is no 30th and 31st day in the month!"), gtk.MESSAGE_WARNING).show()
                    return
                for m in month_leap:
                    if(m == select_month and select_day == 31):
                        MessageDialog(_("Backup Tool"), _("There is no 31st day in the month!"), gtk.MESSAGE_WARNING).show()
                        return
                #the 2nd month of next year
                if((now[1] > select_month) or (now[1] == select_month and now[2] > select_day)):
                    if(select_month == 2 and select_day == 29):
                        if(not ((now[0]+1)%400 == 0 or ((now[0]+1)%4 == 0 and (now[0]+1)%100 != 0))):
                            MessageDialog(_("Backup Tool"), _("There is no 29th day in the the month!"), gtk.MESSAGE_WARNING).show()
                            return            
                #the 2nd of this year
                else:
                    if(select_month == 2 and select_day == 29):
                        if(not (now[0]%400 == 0 or (now[0]%4 == 0 and now[0]%100 != 0))):
                            MessageDialog(_("Backup Tool"), _("There is no 29th day in the the month!"), gtk.MESSAGE_WARNING).show()
                            return
                    #today
                    if(select_month == now[1] and select_day == now[2]):
                        if(select_hour < now[3] or (select_hour == now[3] and select_minute < now[4])):
                            MessageDialog(_("Backup Tool"), _("The time is expired!"), gtk.MESSAGE_WARNING).show()
                            return
                Source += str(select_month) + _("month") + str(select_day) + _("day") + _(" a time")
                if self.remove_systembackup == False:
                    Source += "\n" + _("Backup output:")
                    if(self.wTree.get_widget("combobox_compress1").get_active() == 0):
                        Source += _("Preserve structure always overwrite") 
                    else:
                        Source += _(".tar file not overwrite")
                else:
                    Source += "\n" + _("Remove output:none")
                flag = self.Messaged(Source)
            elif(self.set_periodic):
                if not (self.wTree.get_widget("checkbutton_Mon").get_active() or \
                        self.wTree.get_widget("checkbutton_Tue").get_active() or \
                        self.wTree.get_widget("checkbutton_Wed").get_active() or \
                        self.wTree.get_widget("checkbutton_Thu").get_active() or \
                        self.wTree.get_widget("checkbutton_Fri").get_active() or \
                        self.wTree.get_widget("checkbutton_Sat").get_active() or \
                        self.wTree.get_widget("checkbutton_Sun").get_active()):
                    MessageDialog(_("Backup Tool"), _("Please choose week!"), gtk.MESSAGE_WARNING).show()
                    return
                if(self.wTree.get_widget("checkbutton_Mon").get_active() and \
                   self.wTree.get_widget("checkbutton_Tue").get_active() and \
                   self.wTree.get_widget("checkbutton_Wed").get_active() and \
                   self.wTree.get_widget("checkbutton_Thu").get_active() and \
                   self.wTree.get_widget("checkbutton_Fri").get_active() and \
                   self.wTree.get_widget("checkbutton_Sat").get_active() and \
                   self.wTree.get_widget("checkbutton_Sun").get_active()):
                    Source += _("every day")
                else:
                    Source += _("every")
                    if(self.wTree.get_widget("checkbutton_Mon").get_active()):
                        Source += _("one") + ' '
                    if(self.wTree.get_widget("checkbutton_Tue").get_active()):
                        Source += _("two") + ' '
                    if(self.wTree.get_widget("checkbutton_Wed").get_active()):
                        Source += _("three") + ' '
                    if(self.wTree.get_widget("checkbutton_Thu").get_active()):
                        Source += _("four") + ' '
                    if(self.wTree.get_widget("checkbutton_Fri").get_active()):
                        Source += _("five") + ' '
                    if(self.wTree.get_widget("checkbutton_Sat").get_active()):
                        Source += _("six") + ' '
                    if(self.wTree.get_widget("checkbutton_Sun").get_active()):
                        Source += _("seven") + ' '
                Source += _("a time")
                if self.remove_systembackup == False:
                    Source += "\n" + _("Backup output:")
                    if(self.wTree.get_widget("combobox_compress1").get_active() == 0):
                        Source += _("Preserve structure always overwrite") 
                    else:
                        Source += _(".tar file not overwrite")
                else:
                    Source += "\n" + _("Remove output:none")
                flag = self.Messaged(Source)
            else:
                select_day = self.wTree.get_widget("combobox_day1").get_active() + 1
                Source += _("every month ") + str(select_day) + _(" day") + _(" a time")
                if self.remove_systembackup == False:
                    Source += "\n" + _("Backup output:")
                    if(self.wTree.get_widget("combobox_compress1").get_active() == 0):
                        Source += _("Preserve structure always overwrite")
                    else:
                        Source += _(".tar file not overwrite")
                else:
                    Source += "\n" + _("Remove output:none")
                flag = self.Messaged(Source)
            if(flag):
                model = self.wTree.get_widget("treeview_backup_timer").get_model()
                model.append([Source])
                self.update_flag = True
                self.wTree.get_widget("notebook1").set_current_page(2)
        elif(sel == 19):
            # self.conf_dest should not be empty
            if self.conf_dest == "":
                if self.conf_type <= 2:
                    MessageDialog(_("Backup Tool"), _("Please choose the destination"), gtk.MESSAGE_WARNING).show()
                    return
                else:
                    MessageDialog(_("Backup Tool"), _("Please choose a file to restore from"), gtk.MESSAGE_WARNING).show()
                    return
            # self.conf_type must be conf-compressed file
            if self.conf_type == 3:
                nfsfile = None
                self.tar = None
                try:
                    self.tar = tarfile.open(self.conf_dest, "r")
                    nfsfile = self.tar.getmember(".userbackup")
                    self.tar = None
                except Exception, detail:
                    if(nfsfile is None):
                        MessageDialog(_("Backup Tool"), _("This is not userbackup file."), gtk.MESSAGE_ERROR).show()
                        return
            elif self.conf_type == 4:
                nfsfile = None
                self.tar = None
                try:
                    self.tar = tarfile.open(self.conf_dest, "r")
                    nfsfile = self.tar.getmember(".sysbackup")
                    self.tar = None
                except Exception, detail:
                    if(nfsfile is None):
                        MessageDialog(_("Backup Tool"), _("This is not sysbackup file."), gtk.MESSAGE_ERROR).show()
                        return
            if self.conf_type == 5:
                nfsfile = None
                self.tar = None
                try:
                    self.tar = tarfile.open(self.conf_dest, "r")
                    nfsfile = self.tar.getmember(".allbackup")
                    self.tar = None
                except Exception, detail:
                    if(nfsfile is None):
                        MessageDialog(_("Backup Tool"), _("This is not allbackup file."), gtk.MESSAGE_ERROR).show()
                        return
            conf_type = str(self.conf_type)
            # show overview
            model = gtk.ListStore(str, str)
            model.append(["<b>" + _("Description") + "</b>", self.conf_type_name.get(conf_type)])
            if self.conf_type <= 2:
                model.append(["<b>" + _("Backup configure to") + "</b>", self.conf_dest])
                model.append(["<b>" + _("Attention") + "</b>", _("Please remember your backup destination")])
            else:
                model.append(["<b>" + _("Restore configure from") + "</b>", self.conf_dest])
            self.wTree.get_widget("treeview_overview_conf").set_model(model)
            book.set_current_page(20)
            self.wTree.get_widget("button_forward").hide()
            self.wTree.get_widget("button_apply").show()
            self.wTree.get_widget("button_apply").set_sensitive(True)
        elif(sel == 20):
            self.wTree.get_widget("button_apply").hide()
            self.wTree.get_widget("button_back").hide()
            self.wTree.get_widget("button_back_main").hide()
            if self.conf_type <= 2:
                # start copying
                book.set_current_page(21)
                self.operating = True
                thread = threading.Thread(group=None, target=self.backup_conf, name="NFSBackup-copy", args=(), kwargs={})
                thread.start()
            else:
                # start restoring
                book.set_current_page(23)
                self.operating = True
                thread = threading.Thread(group=None, target=self.restore_conf, name="NFSBackup-restore", args=(), kwargs={})
                thread.start()


    ''' Back button '''
    def back_callback(self, widget):
        book = self.wTree.get_widget("notebook1")
        sel = book.get_current_page()
        self.wTree.get_widget("button_apply").hide()
        self.wTree.get_widget("button_forward").show()
        if(sel == 7 and len(sys.argv) == 2):
            self.wTree.get_widget("button_back").set_sensitive(True)
        if(sel == 6 or sel == 10 or sel == 14 or sel == 2 or sel == 19 or sel == 29 or sel == 25):
            book.set_current_page(0)
            self.wTree.get_widget("button_back").set_sensitive(False)
            self.wTree.get_widget("button_back").hide()
            self.wTree.get_widget("button_forward").hide()
            self.wTree.get_widget("button_about").show()
            self.wTree.get_widget("button_back_main").hide()
            self.wTree.get_widget("button_back_main").set_sensitive(False)
            if(self.tar is not None):
                self.tar.close()
                self.tar = None
        elif(sel == 17):
            book.set_current_page(2)
            self.wTree.get_widget("button_apply").show()
            self.wTree.get_widget("button_apply").set_sensitive(True)
            self.wTree.get_widget("button_forward").hide()
        else:
            sel = sel -1
            if(sel == 0):
                self.wTree.get_widget("button_back").hide()
                self.wTree.get_widget("button_forward").hide()
                self.wTree.get_widget("button_about").show()
                self.wTree.get_widget("button_back_main").hide()
                self.wTree.get_widget("button_back_main").set_sensitive(False)
            if(sel != 2):
                book.set_current_page(sel)
            else:
                book.set_current_page(sel-1)

    ''' Creates a .nfsbackup file (for later restoration) '''
    def create_backup_file(self):
        self.description = "NFSBackup"
        desc = self.wTree.get_widget("entry_desc").get_text()
        if(desc != ""):
            self.description = desc
        try:
            of = os.path.join(self.backup_dest, ".nfsbackup")
            out = open(of, "w")
            lines = [  "source: %s\n" % (self.backup_dest),
                                    #"destination: %s\n" % (self.backup_source),
                                    "file_count: %s\n" % (self.file_count),
                                    "description: %s\n" % (self.description) ]
            out.writelines(lines)
            out.close()
        except:
            return False
        return True

    ''' Creates a configure file (for later restoration) '''
    def create_backup_conf(self):
        self.description = self.conf_type_name.get(str(self.conf_type))
        try:
            if self.conf_type == 0:
                of = os.path.join(self.conf_dest, ".userbackup")
            elif self.conf_type == 1:
                of = os.path.join(self.conf_dest, ".sysbackup")
            elif self.conf_type == 2:
                of = os.path.join(self.conf_dest, ".allbackup")
            out = open(of, "w")
            lines = [  "source: %s\n" % (self.conf_dest),
                                    "file_count: %s\n" % (self.file_count),
                                    "description: %s\n" % (self.description) ]
            out.writelines(lines)
            out.close()
        except:
            return False
        return True
#############################################################################################
    '''add for system backup progress'''
    def update_backup_system_progress(self, current, total, message=None):
        current = float(current)
        total = float(total)
        fraction = float(current / total)
        if(fraction > 1.0):
          fraction = 1.0
        gtk.gdk.threads_enter()
        self.wTree.get_widget("progressbar3").set_fraction(fraction)
        if(message is not None):
            self.wTree.get_widget("progressbar3").set_text(message)
        else:
            self.wTree.get_widget("progressbar3").set_text(str(int(fraction *100)) + "%")
        if(int(fraction *100) == 0):
            self.wTree.get_widget("progressbar3").set_text(str("1%"))
        gtk.gdk.threads_leave()

    '''add for the actual system backup''' 
    def backup_system(self):
        pbar = self.wTree.get_widget("progressbar3")
        label = self.wTree.get_widget("label_current_file2")

        gtk.gdk.threads_enter()
        self.operating = True
	self.system_backup_stat = True
        label.set_label(_("Backing up:"))
        self.wTree.get_widget("progressbar3").show()
        gtk.gdk.threads_leave()
        
        try:
           li = [("%s")%(self.system_dest),",using\n"] 
           fd = open("/usr/lib/nfsbackup/backup_system_stat", "w")
           fd.writelines(li)
           fd.close()
        except Exception, detail:
           print detail

        list1 = [ ]
        list2 = [ ]
        list3 = ["/proc","/dev","/sys","/tmp","/run","/media","/lost+found","/mnt"]
        list = os.listdir("/")
        for i in range(len(list)):
            dir = "/%s"%(list[i])
            if os.path.isdir(dir):
               if dir in list3:
                   continue
               list1.append(dir)
            else:
               list2.append(dir)
        
        filetime = strftime("%Y-%m-%d-%H%M-system_backup", localtime())
        #print filetime
        tarpath = "%s/%s.tar.gz"%(self.system_dest,filetime)
        self.system_tarpath = tarpath
        
	try:
                tar = tarfile.open(tarpath, "w:gz")
                for i in range(len(list1)):
                   if(not self.operating):
                                self.wTree.get_widget("button_cancel").set_sensitive(False)
                                if os.path.isfile(self.system_tarpath):
                                    os.system("rm %s"%(self.system_tarpath))
                                break
                   current = 0
                   self.update_backup_system_progress(0, 1, message=None)
                   for root,dir,files in os.walk(list1[i]):
                     if(not self.operating):
                           if os.path.isfile(self.system_tarpath):
                                    os.system("rm %s"%(self.system_tarpath))
                           break
                     gtk.gdk.threads_enter()
                     current += len(files)
                     gtk.gdk.threads_leave()
                   
                   total = current
                   current = 0

                   for root,dir,files in os.walk(list1[i]):
                      if(not self.operating):
                                self.wTree.get_widget("button_cancel").set_sensitive(False)
                                if os.path.isfile(self.system_tarpath):
                                    os.system("rm %s"%(self.system_tarpath))
                                break
                      gtk.gdk.threads_enter()
                      self.wTree.get_widget("label_current_file_value2").set_text(list1[i])
       
                      gtk.gdk.threads_leave()
		      for file in files:
                        if(not self.operating):
                                self.wTree.get_widget("button_cancel").set_sensitive(False)
                                if os.path.isfile(self.system_tarpath):
                                    os.system("rm %s"%(self.system_tarpath))
                                break
                     
                        fullpath = os.path.join(root,file)                    
			dir = os.path.split(fullpath)
                        #print fullpath
                        if dir[0] == self.system_dest:
                             #print dir[0]
                             continue
                        tar.add(fullpath)
			current += 1
                        #print fullpath,current
			self.update_backup_system_progress(current, total, message=None)
              
                i = 0
                for i in range(len(list2)):
                    tar.add(list2[i])

	        tar.close()
                
                fd = open("/usr/lib/nfsbackup/systembackup_list", "a+")
                n = len(self.system_tarpath)
                new_string = self.system_tarpath[1:n] + "\n"
                fd.writelines(new_string)
                fd.close()
                #self.tar = None
        except Exception, detail:
                if os.path.isfile(self.system_tarpath):
                       os.system("rm %s"%(self.system_tarpath))
            	print detail
                self.errors.append([str(detail), None])

        try:
           li = [("%s")%(self.system_dest),",not using\n"]
           fd = open("/usr/lib/nfsbackup/backup_system_stat", "w")
           fd.writelines(li)
           fd.close()
        except Exception, detail:
           print detail

        gtk.gdk.threads_enter()
        self.system_backup_stat = False
        self.wTree.get_widget("button_cancel").set_sensitive(True)
        label.set_label(_("  "))
        self.wTree.get_widget("label_current_file_value2").set_text(_("Backup system success"))
        self.wTree.get_widget("label_caption_copying2").show()
        self.wTree.get_widget("label_caption_copying2").set_text(_("Backup system success"))
        self.wTree.get_widget("progressbar3").hide()
        gtk.gdk.threads_leave()
        if(not self.operating): 
                if os.path.isfile(self.system_tarpath):
                     os.system("rm %s"%(self.system_tarpath))
                gtk.gdk.threads_enter()
                self.wTree.get_widget("progressbar3").hide()
                self.wTree.get_widget("label_caption_copying2").set_text(_("The task is terminated"))
                self.wTree.get_widget("label_current_file_value2").set_text(_("The task is terminated"))
                gtk.gdk.threads_leave()
        
        gtk.gdk.threads_enter()
        self.operating = False
        gtk.gdk.threads_leave()
        
    
    '''add for system remove'''                
    def remove_systembackup_timer(self,widget):
        self.wTree.get_widget("label_chooce_path").set_text(_("backup destination"))
        self.wTree.get_widget("label_backup_dest1").hide()
        self.wTree.get_widget("label_title_destination1").hide()
        self.wTree.get_widget("scrolledwindow_source1").hide()
        self.wTree.get_widget("label_caption_destination1").hide()
        self.wTree.get_widget("button_addfile1").hide()
        self.wTree.get_widget("button_addfolder1").hide()
        self.wTree.get_widget("button_remove1").hide()
        self.wTree.get_widget("button_addsystem1").hide()
        book = self.wTree.get_widget("notebook1")
        self.remove_systembackup = True
        book.set_current_page(17)
        self.wTree.get_widget("button_back").show()
        self.wTree.get_widget("button_back").set_sensitive(True)
        self.wTree.get_widget("button_forward").show()
        self.wTree.get_widget("button_forward").set_sensitive(True)
        self.wTree.get_widget("button_about").hide()
        self.wTree.get_widget("button_apply").hide()
                     
    def add_systembackup_timer(self, widget):
        self.systembackup_timer = True
        self.remove_systembackup = False
        filename="NFS Desktop Operating System" 
        model = self.wTree.get_widget("treeview_source1").get_model()
        model.append([filename[:], self.fileIcon, filename])                    
                   
####################################################################################################
    ''' Does the actual copying '''
    def backup(self):
        label = self.wTree.get_widget("label_current_file_value")
        #os.chdir(self.backup_source)
        pbar = self.wTree.get_widget("progressbar1")
        gtk.gdk.threads_enter()
        self.wTree.get_widget("button_apply").hide()
        self.wTree.get_widget("button_forward").hide()
        self.wTree.get_widget("button_back").hide()
        label.set_label(_("Calculating..."))
        pbar.set_text(_("Calculating..."))
        gtk.gdk.threads_leave()
        filelist = []
        # get a count of all the files
        total = 0
        

        for row in self.wTree.get_widget("treeview_source").get_model():
            if(not self.operating):
                break
            new_row=os.path.split(row[2])
            if(os.path.isfile(row[2])):
                gtk.gdk.threads_enter()
                pbar.pulse()
                gtk.gdk.threads_leave()
                total += 1
                filelist.append(new_row)
            else:
                os.chdir(new_row[0])
                for top,dirs,files in os.walk(top=row[2],onerror=None, followlinks=self.follow_links):
                    if(not self.operating):
                        break
                    gtk.gdk.threads_enter()             
                    pbar.pulse()
                    gtk.gdk.threads_leave()
                    for f in files:
                        total += 1
                        f = os.path.join(top, f)
                        path = os.path.relpath(f)
                        filelist.append((new_row[0],path))
 
        sztotal = str(total)
        self.file_count = sztotal
        total = float(total)

        current_file = 0
        self.create_backup_file()

        # deletion policy
        del_policy = self.wTree.get_widget("combobox_delete_dest").get_active()

        # find out compression format, if any
        sel = self.wTree.get_widget("combobox_compress").get_active()
        comp = self.wTree.get_widget("combobox_compress").get_model()[sel]
        if(comp[1] is not None):
            tar = None
            filetime = strftime("%Y-%m-%d-%H%M-backup", localtime())
            filename = os.path.join(self.backup_dest, filetime + comp[2] + ".part")
            final_filename = os.path.join(self.backup_dest, filetime + comp[2])
            try:
                tar = tarfile.open(name=filename, dereference=self.follow_links, mode=comp[1], bufsize=1024)
                nfsfile = os.path.join(self.backup_dest, ".nfsbackup")
                tar.add(nfsfile, arcname=".nfsbackup", recursive=False, exclude=None)
            except Exception, detail:
                print detail
                self.errors.append([str(detail), None])
            #backup sources
            for f in filelist:
                os.chdir(f[0])
                if(not self.operating or self.error is not None):
                    break
                rpath = os.path.join(f[0],f[1])
                path = os.path.relpath(rpath)
                target = os.path.join(self.backup_dest, path)
                if(os.path.islink(rpath)):
                    if(self.follow_links):
                        if(not os.path.exists(rpath)):
                            self.update_restore_progress(0, 1, message=_("Skipping broken link"))
                            self.errors.append([rpath, _("Broken link")])
                            continue
                    else:
                        self.update_restore_progress(0, 1, message=_("Skipping link"))
                        current_file += 1
                        continue
                gtk.gdk.threads_enter()
                label.set_label(path)
                self.wTree.get_widget("label_file_count").set_text(str(current_file) + " / " + sztotal)
                gtk.gdk.threads_leave()
                try:
                    underfile = TarFileMonitor(rpath, self.update_backup_progress)
                    finfo = tar.gettarinfo(name=None, arcname=path, fileobj=underfile)
                    tar.addfile(fileobj=underfile, tarinfo=finfo)
                    underfile.close()
                except Exception, detail:
                    print detail
                    self.errors.append([rpath, str(detail)])
                current_file = current_file + 1
            for row in self.wTree.get_widget("treeview_source").get_model():
                new_row=os.path.split(row[2])
                if(os.path.isdir(row[2])):
                    os.chdir(new_row[0])
                    for top,dirs,files in os.walk(top=row[2],onerror=None, followlinks=self.follow_links):
                        if not dirs and not files:
                            rpath = top
                            path = os.path.relpath(rpath)
                            try:
                                tar.add(rpath, arcname=path)
                            except Exception, detail:
                                print detail
                                self.errors.append([rpath, str(detail)])
            try:
                tar.close()
                os.remove(nfsfile)
                os.rename(filename, final_filename)
            except Exception, detail:
                print detail
                self.errors.append([str(detail), None])
        else:
            # Copy to other directory, possibly on another device
            for f in filelist:
                os.chdir(f[0])
                if(not self.operating or self.error is not None):
                    break
                rpath = os.path.join(f[0],f[1])                
                path = os.path.relpath(rpath)
                target = os.path.join(self.backup_dest, path)
                if(os.path.islink(rpath)):
                    if(self.follow_links):
                        if(not os.path.exists(rpath)):
                            self.update_restore_progress(0, 1, message=_("Skipping broken link"))
                            current_file += 1
                            continue
                    else:
                        self.update_restore_progress(0, 1, message=_("Skipping link"))
                        current_file += 1
                        continue
                dir = os.path.split(target)
                if(not os.path.exists(dir[0])):
                    try:
                        os.makedirs(dir[0])
                    except Exception, detail:
                        print detail
                        self.errors.append([dir[0], str(detail)])
                gtk.gdk.threads_enter()
                label.set_label(path)
                self.wTree.get_widget("label_file_count").set_text(str(current_file) + " / " + sztotal)
                gtk.gdk.threads_leave()
                try:
                    if(os.path.exists(target)):
                        if(del_policy == 1):
                            # source size != dest size
                            file1 = os.path.getsize(rpath)
                            file2 = os.path.getsize(target)
                            if(file1 != file2):
                                os.remove(target)
                                self.copy_file(rpath, target, sourceChecksum=None)
                            else:
                                self.update_backup_progress(0, 1, message=_("Skipping identical file"))
                        elif(del_policy == 2):
                            # source time != dest time
                            file1 = os.path.getmtime(rpath)
                            file2 = os.path.getmtime(target)
                            if(file1 != file2):
                                os.remove(target)
                                self.copy_file(rpath, target, sourceChecksum=None)
                            else:
                                self.update_backup_progress(0, 1, message=_("Skipping identical file"))
                        elif(del_policy == 3):
                            # checksums
                            file1 = self.get_checksum(rpath)
                            file2 = self.get_checksum(target)
                            if(file1 not in file2):
                                os.remove(target)
                                self.copy_file(rpath, target, sourceChecksum=file1)
                            else:
                                self.update_backup_progress(0, 1, message=_("Skipping identical file"))
                        elif(del_policy == 4):
                            # always delete
                            os.remove(target)
                            self.copy_file(rpath, target, sourceChecksum=None)
                    else:
                        self.copy_file(rpath, target, sourceChecksum=None)
                    current_file = current_file + 1
                except Exception, detail:
                    print detail
                    self.errors.append([rpath, str(detail)])

                del f
            for row in self.wTree.get_widget("treeview_source").get_model():
                new_row=os.path.split(row[2])
                if(os.path.isdir(row[2])):
                    os.chdir(new_row[0])
                    if(self.preserve_times or self.preserve_perms):
                        #the directorie now to reset the a/m/time
                        path = os.path.relpath(row[2])
                        target = os.path.join(self.backup_dest, path)
                        self.clone_dir(row[2], target)
                    for top,dirs,files in os.walk(top=row[2],onerror=None, followlinks=self.follow_links):
                        if(self.preserve_times or self.preserve_perms):
                            # loop back over the directories now to reset the a/m/time
                            for d in dirs:
                                rpath = os.path.join(top, d)
                                path = os.path.relpath(rpath)
                                target = os.path.join(self.backup_dest, path)
                                self.clone_dir(rpath, target)
                                del d
                '''
                if(self.preserve_times or self.preserve_perms):
                    # loop back over the directories now to reset the a/m/time
                    for d in dirs:
                        rpath = os.path.join(top, d)
                        path = os.path.relpath(rpath)
                        target = os.path.join(self.backup_dest, path)
                        self.clone_dir(rpath, target)
                        del d
                '''

        if(current_file < total):
            self.errors.append([_("Warning: Some files were not saved, copied: %(current_file)d files out of %(total)d total") % {'current_file':current_file, 'total':total}, None])
        if(len(self.errors) > 0):
            gtk.gdk.threads_enter()
            img = self.iconTheme.load_icon("dialog-error", 48, 0)
            self.wTree.get_widget("label_finished_status").set_markup(_("An error occured during the backup"))
            self.wTree.get_widget("image_finished").set_from_pixbuf(img)
            self.wTree.get_widget("treeview_backup_errors").set_model(self.errors)
            self.wTree.get_widget("win_errors").show_all()
            self.wTree.get_widget("notebook1").next_page()
            self.wTree.get_widget("button_back_main").show()
            gtk.gdk.threads_leave()
        else:
            if(not self.operating):
                gtk.gdk.threads_enter()
                img = self.iconTheme.load_icon("dialog-warning", 48, 0)
                self.wTree.get_widget("label_finished_status").set_label(_("The backup was aborted"))
                self.wTree.get_widget("image_finished").set_from_pixbuf(img)
                self.wTree.get_widget("notebook1").next_page()
                self.wTree.get_widget("button_back_main").show()
                gtk.gdk.threads_leave()
            else:
                gtk.gdk.threads_enter()
                label.set_label("Done")
                img = self.iconTheme.load_icon("dialog-information", 48, 0)
                self.wTree.get_widget("label_finished_status").set_label(_("The backup completed successfully"))
                self.wTree.get_widget("image_finished").set_from_pixbuf(img)
                self.wTree.get_widget("notebook1").next_page()
                self.wTree.get_widget("button_back_main").show()
                gtk.gdk.threads_leave()
        self.operating = False

    ''' Does the actual configure copying '''
    def backup_conf(self):
        label = self.wTree.get_widget("label_current_file_value_conf")
        pbar = self.wTree.get_widget("progressbar_conf")
        gtk.gdk.threads_enter()
        self.wTree.get_widget("button_apply").hide()
        self.wTree.get_widget("button_forward").hide()
        self.wTree.get_widget("button_back").hide()
        label.set_label(_("Calculating..."))
        pbar.set_text(_("Calculating..."))
        gtk.gdk.threads_leave()
        filelist = []
        # get a count of all the files
        total = 0
        path_list = []
        #user etcfile
        if self.conf_type == 0:
            path = self.current_userpath
            try:
                h = open('/usr/lib/nfsbackup/useretcfile.txt','r')
                s = h.readlines()
                h.close()
                for l in s:
                    abs_path = path + '/' + l.strip('\n\r')
                    path_list.append(abs_path)
            except Exception, detail:
                print detail
                self.errors.append([str(detail), None])
        #system etcfile
        elif self.conf_type == 1:
            try:
                h = open('/usr/lib/nfsbackup/sysetcfile.txt','r')
                s = h.readlines()
                h.close()
                for l in s:
                    abs_path = l.strip('\n')
                    path_list.append(abs_path)
            except Exception, detail:
                print detail
                self.errors.append([str(detail), None])
        #all etcfile
        else:
            try:
                h = open('/usr/lib/nfsbackup/sysetcfile.txt','r')
                s = h.readlines()
                h.close()
                for l in s:
                    abs_path = l.strip('\n')
                    path_list.append(abs_path)
            except Exception, detail:
                print detail
                self.errors.append([str(detail), None])
            path = self.current_userpath
            try:
                h = open('/usr/lib/nfsbackup/useretcfile.txt','r')
                s = h.readlines()
                h.close()
                for l in s:
                    abs_path = path + '/' + l.strip('\n\r')
                    path_list.append(abs_path)
            except Exception, detail:
                print detail
                self.errors.append([str(detail), None])
        for path_line in path_list:
            if(not self.operating):
                break
            if(os.path.isfile(path_line)):
                gtk.gdk.threads_enter()
                pbar.pulse()
                gtk.gdk.threads_leave()
                total += 1
                filelist.append(path_line)
            else:
                for top,dirs,files in os.walk(top=path_line,onerror=None, followlinks=self.follow_links):
                    if(not self.operating):
                        break
                    gtk.gdk.threads_enter()             
                    pbar.pulse()
                    gtk.gdk.threads_leave()
                    for f in files:
                        total += 1
                        f = os.path.join(top, f)
                        filelist.append(f)

 
        sztotal = str(total)
        self.file_count = sztotal
        total = float(total)

        current_file = 0
        self.create_backup_conf()

        tar = None
        filetime = strftime("%Y-%m-%d-%H%M-", localtime())
        filename = os.path.join(self.conf_dest, filetime + ".tar.part")
        final_filename = os.path.join(self.conf_dest, filetime + self.conf_type_tarname.get(str(self.conf_type))+"_backup.tar")
        try:
            tar = tarfile.open(name=filename, dereference=self.follow_links, mode="w", bufsize=1024)
            if self.conf_type == 0:
                nfsfile = os.path.join(self.conf_dest, ".userbackup")
                tar.add(nfsfile, arcname=".userbackup", recursive=False, exclude=None)
            elif self.conf_type == 1:
                nfsfile = os.path.join(self.conf_dest, ".sysbackup")
                tar.add(nfsfile, arcname=".sysbackup", recursive=False, exclude=None)
            elif self.conf_type == 2:
                nfsfile = os.path.join(self.conf_dest, ".allbackup")
                tar.add(nfsfile, arcname=".allbackup", recursive=False, exclude=None)
        except Exception, detail:
            print detail
            self.errors.append([str(detail), None])
        #backup sources
        for f in filelist:
            if(not self.operating or self.error is not None):
                break
            target = os.path.join(self.conf_dest, f)
            gtk.gdk.threads_enter()
            label.set_label(f)
            self.wTree.get_widget("label_file_count_conf").set_text(str(current_file) + " / " + sztotal)
            gtk.gdk.threads_leave()
            try:
                underfile = TarFileMonitor(f, self.update_backup_progress)
                finfo = tar.gettarinfo(name=None, arcname=f, fileobj=underfile)
                tar.addfile(fileobj=underfile, tarinfo=finfo)
                underfile.close()
            except Exception, detail:
                print detail
                self.errors.append([f, str(detail)])
            current_file = current_file + 1
        try:
            tar.close()
            os.remove(nfsfile)
            os.rename(filename, final_filename)
        except Exception, detail:
            print detail
            self.errors.append([str(detail), None])

        if(current_file < total):
            self.errors.append([_("Warning: Some files were not saved, copied: %(current_file)d files out of %(total)d total") % {'current_file':current_file, 'total':total}, None])
        if(len(self.errors) > 0):
            gtk.gdk.threads_enter()
            img = self.iconTheme.load_icon("dialog-error", 48, 0)
            self.wTree.get_widget("label_finished_status_conf").set_markup(_("An error occured during the backup"))
            self.wTree.get_widget("image_finished_conf").set_from_pixbuf(img)
            self.wTree.get_widget("treeview_backup_errors_conf").set_model(self.errors)
            self.wTree.get_widget("win_errors1").show_all()
            self.wTree.get_widget("notebook1").next_page()
            self.wTree.get_widget("button_back_main").show()
            gtk.gdk.threads_leave()
        else:
            if(not self.operating):
                gtk.gdk.threads_enter()
                img = self.iconTheme.load_icon("dialog-warning", 48, 0)
                self.wTree.get_widget("label_finished_status_conf").set_label(_("The backup was aborted"))
                self.wTree.get_widget("image_finished_conf").set_from_pixbuf(img)
                self.wTree.get_widget("notebook1").next_page()
                self.wTree.get_widget("button_back_main").show()
                gtk.gdk.threads_leave()
            else:
                gtk.gdk.threads_enter()
                label.set_label("Done")
                img = self.iconTheme.load_icon("dialog-information", 48, 0)
                self.wTree.get_widget("label_finished_status_conf").set_label(_("The backup completed successfully"))
                self.wTree.get_widget("image_finished_conf").set_from_pixbuf(img)
                self.wTree.get_widget("notebook1").next_page()
                self.wTree.get_widget("button_back_main").show()
                gtk.gdk.threads_leave()
        self.operating = False

    ''' Update the backup progress bar '''
    def update_backup_progress(self, current, total, message=None):
        current = float(current)
        total = float(total)
        fraction = float(current / total)
        if self.conf_dest == "":
            gtk.gdk.threads_enter()
            self.wTree.get_widget("progressbar1").set_fraction(fraction)
            if(message is not None):
                self.wTree.get_widget("progressbar1").set_text(message)
            else:
                self.wTree.get_widget("progressbar1").set_text(str(int(fraction *100)) + "%")
            gtk.gdk.threads_leave()
        else:
            gtk.gdk.threads_enter()
            self.wTree.get_widget("progressbar_conf").set_fraction(fraction)
            if(message is not None):
                self.wTree.get_widget("progressbar_conf").set_text(message)
            else:
                self.wTree.get_widget("progressbar_conf").set_text(str(int(fraction *100)) + "%")
            gtk.gdk.threads_leave()

    ''' Utility method - copy file, also provides a quick way of aborting a copy, which
        using modules doesn't allow me to do.. '''
    def copy_file(self, source, dest, restore=None, sourceChecksum=None):
        try:
            # represents max buffer size
            BUF_MAX = 16 * 1024 # so we don't get stuck on I/O ops
            errfile = None
            src = open(source, 'rb')
            total = os.path.getsize(source)
            current = 0
            dst = open(dest, 'wb')
            while True:
                if(not self.operating):
                    # Abort!
                    errfile = dest
                    break
                read = src.read(BUF_MAX)
                if(read):
                    dst.write(read)
                    current += len(read)
                    if(restore):
                        self.update_restore_progress(current, total)
                    else:
                        self.update_backup_progress(current, total)
                else:
                    break
            src.close()
            if(errfile):
                # Remove aborted file (avoid corruption)
                dst.close()
                os.remove(errfile)
            else:
                fd = dst.fileno()
                if(self.preserve_perms):
                    # set permissions
                    finfo = os.stat(source)
                    owner = finfo[stat.ST_UID]
                    group = finfo[stat.ST_GID]
                    mode = finfo[stat.ST_MODE]
                    os.fchown(fd, owner, group)
                    os.fchmod(fd, mode)
                    dst.flush()
                    os.fsync(fd)
                    dst.close()
                if(self.preserve_times):
                    finfo = os.stat(source)
                    atime = finfo[stat.ST_ATIME]
                    mtime = finfo[stat.ST_MTIME]
                    os.utime(dest, (atime, mtime))
                else:
                    dst.flush()
                    os.fsync(fd)
                    dst.close()

                if(self.postcheck):
                    if (sourceChecksum is not None):
                        file1 = sourceChecksum
                    else:
                        file1 = self.get_checksum(source, restore)
                    file2 = self.get_checksum(dest, restore)
                    if(file1 not in file2):
                        print _("Checksum Mismatch:") + " [" + file1 + "] [" + file1 + "]"
                        self.errors.append([source, _("Checksum Mismatch")])
        except OSError as bad:
            if(len(bad.args) > 2):
                print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]"
                self.errors.append([bad.args[2], bad.args[1]])
            else:
                print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]"
                self.errors.append([source, bad.args[1]])


    ''' mkdir and clone permissions '''
    def clone_dir(self, source, dest):
        try:
            if(not os.path.exists(dest)):
                os.mkdir(dest)
            if(self.preserve_perms):
                finfo = os.stat(source)
                owner = finfo[stat.ST_UID]
                group = finfo[stat.ST_GID]
                os.chown(dest, owner, group)
            if(self.preserve_times):
                finfo = os.stat(source)
                atime = finfo[stat.ST_ATIME]
                mtime = finfo[stat.ST_MTIME]
                os.utime(dest, (atime, mtime))
        except OSError as bad:
            if(len(bad.args) > 2):
                print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]"
                self.errors.append([bad.args[2], bad.args[1]])
            else:
                print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]"
                self.errors.append([source, bad.args[1]])

    ''' Grab the checksum for the input filename and return it '''
    def get_checksum(self, source, restore=None):
        MAX_BUF = 16*1024
        current = 0
        try:
            check = hashlib.sha1()
            input = open(source, "rb")
            total = os.path.getsize(source)
            while True:
                if(not self.operating):
                    return None
                read = input.read(MAX_BUF)
                if(not read):
                    break
                check.update(read)
                current += len(read)
                if(restore):
                    self.update_restore_progress(current, total, message=_("Calculating checksum"))
                else:
                    self.update_backup_progress(current, total, message=_("Calculating checksum"))
            input.close()
            return check.hexdigest()
        except OSError as bad:
            if(len(bad.args) > 2):
                print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + bad.args[2] + "]"
                self.errors.append([bad.args[2], bad.args[1]])
            else:
                print "{" + str(bad.args[0]) + "} " + bad.args[1] + " [" + source + "]"
                self.errors.append([source, bad.args[1]])
        return None

    ''' Grabs checksum for fileobj type object '''
    def get_checksum_for_file(self, source):
        MAX_BUF = 16*1024
        current = 0
        total = source.size
        try:
            check = hashlib.sha1()
            while True:
                if(not self.operating):
                    return None
                read = source.read(MAX_BUF)
                if(not read):
                    break
                check.update(read)
                current += len(read)
                self.update_restore_progress(current, total, message=_("Calculating checksum"))
            source.close()
            return check.hexdigest()
        except Exception, detail:
            self.errors.append([source, str(detail)])
            print detail
        return None

    ''' Update the restore progress bar '''
    def update_restore_progress(self, current, total, message=None):
        current = float(current)
        total = float(total)
        fraction = float(current / total)
        gtk.gdk.threads_enter()
        self.wTree.get_widget("progressbar_restore").set_fraction(fraction)
        if(message is not None):
            self.wTree.get_widget("progressbar_restore").set_text(message)
        else:
            self.wTree.get_widget("progressbar_restore").set_text(str(int(fraction *100)) + "%")
        gtk.gdk.threads_leave()

    ''' prepare the restore, reads the .nfsbackup file if present '''
    def prepare_restore(self):
        if(self.restore_archive):
            # restore archives.
            if(self.tar is not None):
                gtk.gdk.threads_enter()
                self.wTree.get_widget("notebook1").set_current_page(7)
                self.wTree.get_widget("button_forward").hide()
                self.wTree.get_widget("button_apply").show()
                self.wTree.get_widget("button_apply").set_sensitive(True)
                gtk.gdk.threads_leave()
                return
            gtk.gdk.threads_enter()
            self.wTree.get_widget("main_window").set_sensitive(False)
            self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
            gtk.gdk.threads_leave()
            self.conf = mINIFile()
            try:
                self.tar = tarfile.open(self.restore_source, "r")
                nfsfile = self.tar.getmember(".nfsbackup")
                if(nfsfile is None):
                    print "Processing a backup not created with this tool"
                    self.conf.description = _("(Not created with the Backup Tool)")
                    self.conf.file_count = -1
                else:
                    mfile = self.tar.extractfile(nfsfile)
                    self.conf.load_from_list(mfile.readlines())
                    mfile.close()

                gtk.gdk.threads_enter()
                self.wTree.get_widget("label_overview_description_value").set_label(self.conf.description)
                self.wTree.get_widget("button_back").set_sensitive(True)
                self.wTree.get_widget("button_forward").hide()
                self.wTree.get_widget("button_apply").show()
                self.wTree.get_widget("button_apply").set_sensitive(True)
                self.wTree.get_widget("notebook1").set_current_page(7)
                gtk.gdk.threads_leave()

            except Exception, detail:
                print detail
        else:
            # Restore from directory
            self.conf = mINIFile()
            try:
                mfile = os.path.join(self.restore_source, ".nfsbackup")
                if(not os.path.exists(mfile)):
                    print "Processing a backup not created with this tool"
                    self.conf.description = _("(Not created with the Backup Tool)")
                    self.conf.file_count = -1
                else:
                    self.conf.load_from_file(mfile)

                gtk.gdk.threads_enter()
                self.wTree.get_widget("label_overview_description_value").set_label(_("Restore files"))
                self.wTree.get_widget("button_back").set_sensitive(True)
                self.wTree.get_widget("button_forward").hide()
                self.wTree.get_widget("button_apply").show()
                self.wTree.get_widget("button_apply").set_sensitive(True)
                self.wTree.get_widget("notebook1").set_current_page(7)
                gtk.gdk.threads_leave()

            except Exception, detail:
                print detail
        if(not self.restore_archive):
            sources = self.wTree.get_widget("treeview_source_restore").get_model()
            self.restore_source = ""
            for row in sources:
                self.restore_source += row[2] + "  "
        gtk.gdk.threads_enter()
        self.wTree.get_widget("label_overview_source_value").set_label(self.restore_source)
        self.wTree.get_widget("label_overview_dest_value").set_label(self.restore_dest)
        self.wTree.get_widget("main_window").set_sensitive(True)
        self.wTree.get_widget("main_window").window.set_cursor(None)
        gtk.gdk.threads_leave()

    ''' extract file from archive '''
    def extract_file(self, source, dest, record):
        MAX_BUF = 512
        current = 0
        total = record.size
        errflag = False
        while True:
            if(not self.operating):
                errflag = True
                break
            read = source.read(MAX_BUF)
            if(not read):
                break
            dest.write(read)
            current += len(read)
            self.update_restore_progress(current, total)
        source.close()
        if(errflag):
            dest.close()
            os.remove(target)
        else:
            # set permissions
            fd = dest.fileno()
            os.fchown(fd, record.uid, record.gid)
            os.fchmod(fd, record.mode)
            dest.flush()
            os.fsync(fd)
            dest.close()
            os.utime(dest.name, (record.mtime, record.mtime))

    ''' Restore from archive '''
    def restore(self):
        self.preserve_perms = True
        self.preserve_times = True
        self.postcheck = True
        gtk.gdk.threads_enter()
        self.wTree.get_widget("button_apply").hide()
        self.wTree.get_widget("button_forward").hide()
        self.wTree.get_widget("button_back").hide()
        gtk.gdk.threads_leave()

        del_policy = self.wTree.get_widget("combobox_restore_del").get_active()
        gtk.gdk.threads_enter()
        pbar = self.wTree.get_widget("progressbar_restore")
        pbar.set_text(_("Calculating..."))
        label = self.wTree.get_widget("label_restore_status_value")
        label.set_label(_("Calculating..."))
        gtk.gdk.threads_leave()

        # restore from archive
        self.error = None
        if(self.restore_archive):
            os.chdir(self.restore_dest)
            sztotal = self.conf.file_count
            total = float(sztotal)
            if(total == -1):
                tmp = len(self.tar.getmembers())
                szttotal = str(tmp)
                total = float(tmp)
            current_file = 0
            MAX_BUF = 1024
            for record in self.tar.getmembers():
                if(not self.operating):
                    break
                if(record.name == ".nfsbackup"):
                    # skip nfsbackup file
                    continue
                gtk.gdk.threads_enter()
                label.set_label(record.name)
                gtk.gdk.threads_leave()
                if(record.isdir()):
                    target = os.path.join(self.restore_dest, record.name)
                    if(not os.path.exists(target)):
                        try:
                            os.mkdir(target)
                            os.chown(target, record.uid, record.gid)
                            os.chmod(target, record.mode)
                            os.utime(target, (record.mtime, record.mtime))
                        except Exception, detail:
                            print detail
                            self.errors.append([target, str(detail)])
                if(record.isreg()):
                    target = os.path.join(self.restore_dest, record.name)
                    dir = os.path.split(target)
                    if(not os.path.exists(dir[0])):
                        try:
                            os.makedirs(dir[0])
                        except Exception, detail:
                            print detail
                            self.errors.append([dir[0], str(detail)])
                    gtk.gdk.threads_enter()
                    self.wTree.get_widget("label_restore_file_count").set_text(str(current_file) + " / " + sztotal)
                    gtk.gdk.threads_leave()
                    try:
                        if(os.path.exists(target)):
                            if(del_policy == 1):
                                # source size != dest size
                                file1 = record.size
                                file2 = os.path.getsize(target)
                                if(file1 != file2):
                                    os.remove(target)
                                    gz = self.tar.extractfile(record)
                                    out = open(target, "wb")
                                    self.extract_file(gz, out, record)
                                else:
                                    self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                            elif(del_policy == 2):
                                # source time != dest time
                                file1 = record.mtime
                                file2 = os.path.getmtime(target)
                                if(file1 != file2):
                                    os.remove(target)
                                    gz = self.tar.extractfile(record)
                                    out = open(target, "wb")
                                    self.extract_file(gz, out, record)
                                else:
                                    self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                            elif(del_policy == 3):
                                # checksums
                                gz = self.tar.extractfile(record)
                                file1 = self.get_checksum_for_file(gz)
                                file2 = self.get_checksum(target)
                                if(file1 not in file2):
                                    os.remove(target)
                                    out = open(target, "wb")
                                    gz.close()
                                    gz = self.tar.extractfile(record)
                                    self.extract_file(gz, out, record)
                                else:
                                    self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                            elif(del_policy == 4):
                                # always delete
                                os.remove(target)
                                gz = self.tar.extractfile(record)
                                out = open(target, "wb")
                                self.extract_file(gz, out, record)
                        else:
                            gz = self.tar.extractfile(record)
                            out = open(target, "wb")
                            self.extract_file(gz, out, record)
                        current_file = current_file + 1
                    except Exception, detail:
                        print detail
                        self.errors.append([record.name, str(detail)])
            try:
                self.tar.close()
            except:
                pass
        else:
            # restore backup from dir.
            sources = self.wTree.get_widget("treeview_source_restore").get_model()
            current_file = 0
            total = 0
            for row in sources:
                self.restore_source = row[2]
                if(os.path.isdir(self.restore_source)):
                    resotre_path = os.path.split(self.restore_source) 
                    os.chdir(resotre_path[0])
                    for top,dirs,files in os.walk(top=self.restore_source,onerror=None, followlinks=self.follow_links):
                        pbar.pulse()
                        for f in files:
                            if(not self.operating):
                                break
                            total += 1
                else:
                     pbar.pulse()
                     total += 1
            sztotal = str(total)
            total = float(total)

            for row in sources:
                self.restore_source = row[2]
                resotre_path = os.path.split(self.restore_source) 
                os.chdir(resotre_path[0])
                if(os.path.isdir(self.restore_source)):
                    #clone restore_source
                    path = os.path.relpath(self.restore_source)
                    target = os.path.join(self.restore_dest, path)
                    dir = os.path.split(target)
                    self.clone_dir(self.restore_source, target)

                    #for top,dirs,files in os.walk(top=self.restore_source,topdown=False,onerror=None,followlinks=self.follow_links):
                    for top,dirs,files in os.walk(top=self.restore_source,onerror=None,followlinks=self.follow_links):
                        if(not self.operating):
                            break
                        for f in files:
                            if ".nfsbackup" in f:
                                continue
                            rpath = os.path.join(top, f)
                            path = os.path.relpath(rpath)
                            target = os.path.join(self.restore_dest, path)
                            dir = os.path.split(target)
                            if(not os.path.exists(dir[0])):
                                try:
                                    os.makedirs(dir[0])
                                except Exception, detail:
                                    print detail
                                    self.errors.append([dir[0], str(detail)])
                            current_file = current_file + 1
                            gtk.gdk.threads_enter()
                            label.set_label(path)
                            gtk.gdk.threads_leave()
                            self.wTree.get_widget("label_restore_file_count").set_text(str(current_file) + " / " + sztotal)
                            try:
                                if(os.path.exists(target)):
                                    if(del_policy == 1):
                                        # source size != dest size
                                        file1 = os.path.getsize(rpath)
                                        file2 = os.path.getsize(target)
                                        if(file1 != file2):
                                            os.remove(target)
                                            self.copy_file(rpath, target, restore=True, sourceChecksum=None)
                                        else:
                                            self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                                    elif(del_policy == 2):
                                        # source time != dest time
                                        file1 = os.path.getmtime(rpath)
                                        file2 = os.path.getmtime(target)
                                        if(file1 != file2):
                                            os.remove(target)
                                            self.copy_file(rpath, target, restore=True, sourceChecksum=None)
                                        else:
                                            self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                                    elif(del_policy == 3):
                                        # checksums (check size first)
                                        if(os.path.getsize(rpath) == os.path.getsize(target)):
                                            file1 = self.get_checksum(rpath)
                                            file2 = self.get_checksum(target)
                                            if(file1 not in file2):
                                                os.remove(target)
                                                self.copy_file(rpath, target, restore=True, sourceChecksum=file1)
                                            else:
                                                self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                                        else:
                                            os.remove(target)
                                            self.copy_file(rpath, target, restore=True, sourceChecksum=None)
                                    elif(del_policy == 4):
                                        # always delete
                                        os.remove(target)
                                        self.copy_file(rpath, target, restore=True, sourceChecksum=None)
                                else:
                                    self.copy_file(rpath, target, restore=True, sourceChecksum=None)
                                current_file += 1
                            except Exception, detail:
                                print detail
                                self.errors.append([rpath, str(detail)])
                            del f
                        if(self.preserve_times or self.preserve_perms):
                            # loop back over the directories now to reset the a/m/time
                            for d in dirs:
                                rpath = os.path.join(top, d)
                                path = os.path.relpath(rpath)
                                target = os.path.join(self.restore_dest, path)
                                self.clone_dir(rpath, target)
                                del d
                else:
                    if ".nfsbackup" in self.restore_source:
                        continue
                    path = os.path.relpath(self.restore_source)
                    target = os.path.join(self.restore_dest, path)
                    current_file = current_file + 1
                    gtk.gdk.threads_enter()
                    label.set_label(path)
                    gtk.gdk.threads_leave()
                    self.wTree.get_widget("label_restore_file_count").set_text(str(current_file) + " / " + sztotal)
                    try:
                        if(os.path.exists(target)):
                            if(del_policy == 1):
                                # source size != dest size
                                file1 = os.path.getsize(self.restore_source)
                                file2 = os.path.getsize(target)
                                if(file1 != file2):
                                    os.remove(target)
                                    self.copy_file(self.restore_source, target, restore=True, sourceChecksum=None)
                                else:
                                    self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                            elif(del_policy == 2):
                                # source time != dest time
                                file1 = os.path.getmtime(self.restore_source)
                                file2 = os.path.getmtime(target)
                                if(file1 != file2):
                                    os.remove(target)
                                    self.copy_file(self.restore_source, target, restore=True, sourceChecksum=None)
                                else:
                                    self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                            elif(del_policy == 3):
                                # checksums (check size first)
                                if(os.path.getsize(self.restore_source) == os.path.getsize(target)):
                                    file1 = self.get_checksum(self.restore_source)
                                    file2 = self.get_checksum(target)
                                    if(file1 not in file2):
                                        os.remove(target)
                                        self.copy_file(self.restore_source, target, restore=True, sourceChecksum=file1)
                                    else:
                                        self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                                else:
                                    os.remove(target)
                                    self.copy_file(self.restore_source, target, restore=True, sourceChecksum=None)
                            elif(del_policy == 4):
                                # always delete
                                os.remove(target)
                                self.copy_file(self.restore_source, target, restore=True, sourceChecksum=None)
                        else:
                            self.copy_file(self.restore_source, target, restore=True, sourceChecksum=None)
                        current_file += 1
                    except Exception, detail:
                        print detail
                        self.errors.append([self.restore_source, str(detail)])

        if(current_file < total):
            self.error = _("Warning: Some filed were not restored, copied: %(current_file)d files out of %(total)d total") % {'current_file':current_file, 'total':total}
        if(len(self.errors) > 0):
            gtk.gdk.threads_enter()
            self.wTree.get_widget("label_restore_finished_value").set_label(_("An error occured during the restoration"))
            img = self.iconTheme.load_icon("dialog-error", 48, 0)
            self.wTree.get_widget("image_restore_finished").set_from_pixbuf(img)
            self.wTree.get_widget("treeview_restore_errors").set_model(self.errors)
            self.wTree.get_widget("win_restore_errors").show_all()
            self.wTree.get_widget("button_back_main").show()
            self.wTree.get_widget("notebook1").next_page()
            gtk.gdk.threads_leave()
        else:
            if(not self.operating):
                gtk.gdk.threads_enter()
                img = self.iconTheme.load_icon("dialog-warning", 48, 0)
                self.wTree.get_widget("label_restore_finished_value").set_label(_("The restoration was aborted"))
                self.wTree.get_widget("image_restore_finished").set_from_pixbuf(img)
                self.wTree.get_widget("notebook1").next_page()
                self.wTree.get_widget("button_back_main").show()
                gtk.gdk.threads_leave()
            else:
                gtk.gdk.threads_enter()
                label.set_label("Done")
                pbar.set_text("Done")
                self.wTree.get_widget("label_restore_finished_value").set_label(_("The restoration completed successfully"))
                img = self.iconTheme.load_icon("dialog-information", 48, 0)
                self.wTree.get_widget("image_restore_finished").set_from_pixbuf(img)
                self.wTree.get_widget("notebook1").next_page()
                self.wTree.get_widget("button_back_main").show()
                gtk.gdk.threads_leave()
        self.operating = False

    ''' Restore configure from archive '''
    def restore_conf(self):
        gtk.gdk.threads_enter()
        self.wTree.get_widget("button_apply").hide()
        self.wTree.get_widget("button_forward").hide()
        self.wTree.get_widget("button_back").hide()
        gtk.gdk.threads_leave()

        gtk.gdk.threads_enter()
        pbar = self.wTree.get_widget("progressbar_restore_conf")
        pbar.set_text(_("Calculating..."))
        label = self.wTree.get_widget("label_restore_current_value_conf")
        label.set_label(_("Calculating..."))
        gtk.gdk.threads_leave()

        # restore from archive
        self.conf = mINIFile()
        try:
            self.tar = tarfile.open(self.conf_dest, "r")
            if self.conf_type == 3:
                nfsfile = self.tar.getmember(".userbackup")
            elif self.conf_type == 4:
                nfsfile = self.tar.getmember(".sysbackup")
            elif self.conf_type == 5:
                nfsfile = self.tar.getmember(".allbackup")
            if(nfsfile is None):
                self.conf.file_count = -1
            mfile = self.tar.extractfile(nfsfile)
            self.conf.load_from_list(mfile.readlines())
            mfile.close()
        except Exception, detail:
            print detail

        self.error = None
        sztotal = self.conf.file_count
        total = float(sztotal)
        if(total == -1):
            tmp = len(self.tar.getmembers())
            szttotal = str(tmp)
            total = float(tmp)
        current_file = 0
        MAX_BUF = 1024
        for record in self.tar.getmembers():
            if(not self.operating):
                break
            if(record.name == ".userbackup" or record.name == ".sysbackup" or record.name == ".allbackup"):
                # skip nfsbackup file
                continue
            gtk.gdk.threads_enter()
            label.set_label(record.name)
            gtk.gdk.threads_leave()
            if(record.isdir()):
                target = os.path.join("/", record.name)
                if(not os.path.exists(target)):
                    try:
                        os.mkdir(target)
                        os.chown(target, record.uid, record.gid)
                        os.chmod(target, record.mode)
                        os.utime(target, (record.mtime, record.mtime))
                    except Exception, detail:
                        print detail
                        self.errors.append([target, str(detail)])
            if(record.isreg()):
                target = os.path.join("/", record.name)
                dir = os.path.split(target)
                if(not os.path.exists(dir[0])):
                    try:
                        os.makedirs(dir[0])
                    except Exception, detail:
                        print detail
                        self.errors.append([dir[0], str(detail)])
                gtk.gdk.threads_enter()
                self.wTree.get_widget("label_restore_file_count_conf").set_text(str(current_file) + " / " + sztotal)
                gtk.gdk.threads_leave()
                try:
                    if(os.path.exists(target)):
                        # checksums
                        gz = self.tar.extractfile(record)
                        file1 = self.get_checksum_for_file(gz)
                        file2 = self.get_checksum(target)
                        if(file1 not in file2):
                            os.remove(target)
                            out = open(target, "wb")
                            gz.close()
                            gz = self.tar.extractfile(record)
                            self.extract_file(gz, out, record)
                            print "checksum is not equal"
                        else:
                            self.update_restore_progress(0, 1, message=_("Skipping identical file"))
                    else:
                        gz = self.tar.extractfile(record)
                        out = open(target, "wb")
                        self.extract_file(gz, out, record)
                    current_file = current_file + 1
                except Exception, detail:
                    print detail
                    self.errors.append([record.name, str(detail)])
        try:
            self.tar.close()
        except:
            pass

        if(current_file < total):
            self.error = _("Warning: Some filed were not restored, copied: %(current_file)d files out of %(total)d total") % {'current_file':current_file, 'total':total}
        if(len(self.errors) > 0):
            gtk.gdk.threads_enter()
            self.wTree.get_widget("label_restore_finished_value_conf").set_label(_("An error occured during the restoration"))
            img = self.iconTheme.load_icon("dialog-error", 48, 0)
            self.wTree.get_widget("image_restore_finished_conf").set_from_pixbuf(img)
            self.wTree.get_widget("treeview_restore_errors_conf").set_model(self.errors)
            self.wTree.get_widget("win_restore_errors1").show_all()
            self.wTree.get_widget("notebook1").next_page()
            self.wTree.get_widget("button_back_main").show()
            gtk.gdk.threads_leave()
        else:
            if(not self.operating):
                gtk.gdk.threads_enter()
                img = self.iconTheme.load_icon("dialog-warning", 48, 0)
                self.wTree.get_widget("label_restore_finished_value_conf").set_label(_("The restoration was aborted"))
                self.wTree.get_widget("image_restore_finished_conf").set_from_pixbuf(img)
                self.wTree.get_widget("notebook1").next_page()
                self.wTree.get_widget("button_back_main").show()
                gtk.gdk.threads_leave()
            else:
                gtk.gdk.threads_enter()
                label.set_label("Done")
                pbar.set_text("Done")
                self.wTree.get_widget("label_restore_finished_value_conf").set_label(_("The restoration completed successfully"))
                img = self.iconTheme.load_icon("dialog-information", 48, 0)
                self.wTree.get_widget("image_restore_finished_conf").set_from_pixbuf(img)
                self.wTree.get_widget("notebook1").next_page()
                self.wTree.get_widget("button_back_main").show()
                gtk.gdk.threads_leave()
        self.operating = False

        ''' load the package list '''
    def load_packages(self):
        gtk.gdk.threads_enter()
        model = gtk.ListStore(bool, str, str)
        model.set_sort_column_id(1, gtk.SORT_ASCENDING)
        self.wTree.get_widget("treeview_packages").set_model(model)
        self.wTree.get_widget("main_window").set_sensitive(False)
        self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        gtk.gdk.threads_leave()
        try:
            p = subprocess.Popen("aptitude search ~M", shell=True, stdout=subprocess.PIPE)
            self.blacklist = list()
            for l in p.stdout:
                l = l.rstrip("\n")
                l = l.split(" ")
                self.blacklist.append(l[2])
            bl = open("/usr/lib/nfsbackup/software-selections.list", "r")
            for l in bl.readlines():
                if(l.startswith("#")):
                    # ignore comments
                    continue
                l = l.rstrip("\n")
                self.blacklist.append(l)
            bl.close()
        except Exception, detail:
            print detail
        cache = apt.Cache()
        for pkg in cache:
            if(pkg.installed):
                if(self.is_manual_installed(pkg.name) == True):
                    desc = "<big>" + pkg.name + "</big>\n<small>" + pkg.installed.summary.replace("&", "&amp;") + "</small>"
                    gtk.gdk.threads_enter()
                    model.append([True, pkg.name, desc])
                    gtk.gdk.threads_leave()
        gtk.gdk.threads_enter()
        self.wTree.get_widget("main_window").set_sensitive(True)
        self.wTree.get_widget("main_window").window.set_cursor(None)
        gtk.gdk.threads_leave()

    def Messagedia(self,message):
        messag = "<big>" + _("Are you sure to remove :") + "</big>\r\n"
        messag += message
        dialog = gtk.MessageDialog(None, 0, gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, messag)
        
        dialog.set_markup(messag)
        dialog.set_title(_("Backup Tool"))
        dialog.set_position(gtk.WIN_POS_CENTER)
        response = dialog.run()
        if response == gtk.RESPONSE_YES:
            flag = True
        else:
            flag = False
        dialog.destroy()
        return flag

        ''' load the backup-timer list '''
    def load_backup_timer(self):
        gtk.gdk.threads_enter()
        model = gtk.ListStore(str)
        #model.set_sort_column_id(1, gtk.SORT_ASCENDING)
        self.wTree.get_widget("treeview_backup_timer").set_model(model)
        self.wTree.get_widget("main_window").set_sensitive(False)
        self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        gtk.gdk.threads_leave()
        try:
            bl = open("/usr/lib/nfsbackup/cronfile", "r")
            #bl = open("./cronfile", "r")
            for l in bl.readlines():
                if(l.startswith("#")):
                    # ignore comments
                    continue
                l = l.rstrip("\r\n")
                timerlist = l.split(' ')
                #handle time
                if(timerlist[0] == '*'):
                    minute = '00'
                else:
                    if(string.atoi(timerlist[0]) < 10):
                        minute = '0' + timerlist[0]
                    else:
                        minute = timerlist[0]
                if(timerlist[1] == '*'):
                    hour = '0'
                else:
                    hour = timerlist[1]
                if l.find("remove_timer.py")> -1:
                    Source = _("remove task : ")
                else:
                    Source = _("Backup-timer source")
                
                if l.find("systembackup.py") > -1:
                    Source += "NFS Desktop Operating System\n"
                elif l.find("remove_timer.py")> -1:
                    Source += "remove old Operating Systembackup\n"
                else:
                    for timer in timerlist[6:-1]:
                        if(timer == timerlist[6]):
                            Source += timer + "\n"
                        else:
                            Source += "               " + timer + "\n"
                if l.find("remove_timer.py")> -1:
                    Source +=_("System Backup path : ") + timerlist[-1]
                else:
                    Source +=_("Backup-timer destination") + timerlist[-1]
                Source += "\n" + _("Time") + hour + ":" + minute + "\n" + _("Strategy")
                if(timerlist[3] != '*'):
                    Source += timerlist[3] + _("month") + timerlist[2] + _("day")
                elif(timerlist[2] != '*' and timerlist[3] == '*'):
                    Source += _("every month ") + timerlist[2] + _(" day ")
                else:
                    if(timerlist[4] == '*'):
                        Source += _("every day")
                    else:
                        Source += _("every")
                        week = timerlist[4].split(',')
                        for w in week:
                            if(w == '1'):
                                Source += _("one") + ' '
                            if(w == '2'):                           
                                Source += _("two") + ' '
                            if(w == '3'):
                                Source += _("three") + ' '
                            if(w == '4'):
                                Source += _("four") + ' '
                            if(w == '5'):
                                Source += _("five") + ' '
                            if(w == '6'):
                                Source += _("six") + ' '
                            if(w == '7'):
                                Source += _("seven") + ' '
                if l.find("remove_timer.py")> -1:
                    Source += _("remove a time")
                    Source += "\n" + _("output:")
                else:
                    Source += _("backup a time")
                    Source += "\n" + _("Backup output:")
                if(timerlist[5] == "/usr/lib/nfsbackup/tar.py"):
                    Source += _(".tar file not overwrite")
                else:
                    Source += _("Preserve structure always overwrite")
                gtk.gdk.threads_enter()
                model.append([Source])
                gtk.gdk.threads_leave()
            bl.close()
        except Exception, detail:
            print detail

        gtk.gdk.threads_enter()
        self.wTree.get_widget("main_window").set_sensitive(True)
        self.wTree.get_widget("main_window").window.set_cursor(None)
        gtk.gdk.threads_leave()

    ''' Add a backup-timer '''
    def add_backuptimer(self, widget):
        self.wTree.get_widget("label_chooce_path").set_text(_("backup destination"))
        self.wTree.get_widget("scrolledwindow_source1").show()
        self.wTree.get_widget("treeview_source1").show()
        self.wTree.get_widget("label_caption_destination1").show()
        self.wTree.get_widget("button_addfile1").show()
        self.wTree.get_widget("button_addfolder1").show()
        self.wTree.get_widget("button_remove1").show()
        self.wTree.get_widget("button_addsystem1").show()
        self.systembackup_timer = False
        self.remove_systembackup = False
        book = self.wTree.get_widget("notebook1")
        book.set_current_page(17)
        self.wTree.get_widget("button_back").show()
        self.wTree.get_widget("button_back").set_sensitive(True)
        self.wTree.get_widget("button_forward").show()
        self.wTree.get_widget("button_forward").set_sensitive(True)
        self.wTree.get_widget("button_about").hide()
        self.wTree.get_widget("button_apply").hide()
    ''' Remove the backup-timer '''
    def remove_backuptimer(self, widget):
        model = self.wTree.get_widget("treeview_backup_timer").get_model()
        selection = self.wTree.get_widget("treeview_backup_timer").get_selection()
        selected_rows = selection.get_selected_rows()[1]
        if len(selected_rows) <= 0:
            return
        message = selection.get_selected_rows()[0][0][0]
        remove_flag = self.Messagedia(message)
        if(remove_flag == True):
            # don't you just hate python? :) Here's another hack for python not to get confused with its own paths while we're deleting multiple stuff.
            # actually.. gtk is probably to blame here.
            args = [(model.get_iter(path)) for path in selected_rows]
            for iter in args:
                model.remove(iter)
            self.update_flag = True

    ''' Is the package manually installed? '''
    def is_manual_installed(self, pkgname):
        for b in self.blacklist:
            if(pkgname == b):
                return False
        return True

    ''' toggled (update model)'''
    def toggled_cb(self, ren, path, treeview):
        model = treeview.get_model()
        iter = model.get_iter(path)
        if (iter != None):
            checked = model.get_value(iter, 0)
            model.set_value(iter, 0, (not checked))

    ''' for the packages treeview '''
    def celldatafunction_checkbox(self, column, cell, model, iter):
        checked = model.get_value(iter, 0)
        cell.set_property("active", checked)

    ''' Show filechooser for package backup '''
    def show_package_choose(self, w):
        dialog = gtk.FileChooserDialog(_("Backup Tool"), None, gtk.FILE_CHOOSER_ACTION_SAVE, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_SAVE, gtk.RESPONSE_OK))
        dialog.set_current_folder(home)
        dialog.set_select_multiple(False)
        if dialog.run() == gtk.RESPONSE_OK:
            self.package_dest = dialog.get_filename()
            self.wTree.get_widget("entry_package_dest").set_text(self.package_dest)
        dialog.destroy()

    ''' "backup" the package selection '''
    def backup_packages(self):
        pbar = self.wTree.get_widget("progressbar_packages")
        lab = self.wTree.get_widget("label_current_package_value")
        gtk.gdk.threads_enter()
        pbar.set_text(_("Calculating..."))
        lab.set_label(_("Calculating..."))
        gtk.gdk.threads_leave()
        model = self.wTree.get_widget("treeview_packages").get_model()
        total = 0
        count = 0
        for row in model:
            if(not self.operating or self.error is not None):
                break
            if(not row[0]):
                continue
            total += 1
        pbar.set_text("%d / %d" % (count, total))
        try:
            filetime = strftime("%Y-%m-%d-%H%M-package.list", localtime())
            filename = "software_selection_%s@%s" % (commands.getoutput("hostname"), filetime)
            out = open(os.path.join(self.package_dest, filename), "w")
            for row in model:
                if(not self.operating or self.error is not None):
                    break
                if(row[0]):
                    count += 1
                    out.write("%s\t%s\n" % (row[1], "install"))
                    gtk.gdk.threads_enter()
                    pbar.set_text("%d / %d" % (count, total))
                    pbar.set_fraction(float(count / total))
                    lab.set_label(row[1])
                    gtk.gdk.threads_leave()
            out.close()
            os.system("chmod a+rx " + self.package_dest)
            os.system("chmod a+rw " + os.path.join(self.package_dest, filename))
        except Exception, detail:
            self.error = str(detail)

        if(self.error is not None):
            gtk.gdk.threads_enter()
            self.wTree.get_widget("label_packages_done_value").set_label(_("An error occured during the backup:") + "\n" + self.error)
            img = self.iconTheme.load_icon("dialog-error", 48, 0)
            self.wTree.get_widget("image_packages_done").set_from_pixbuf(img)
            self.wTree.get_widget("notebook1").next_page()
            gtk.gdk.threads_leave()
        else:
            if(not self.operating):
                gtk.gdk.threads_enter()
                img = self.iconTheme.load_icon("dialog-warning", 48, 0)
                self.wTree.get_widget("label_packages_done_value").set_label(_("The backup was aborted"))
                self.wTree.get_widget("image_packages_done").set_from_pixbuf(img)
                self.wTree.get_widget("notebook1").next_page()
                gtk.gdk.threads_leave()
            else:
                gtk.gdk.threads_enter()
                lab.set_label("Done")
                pbar.set_text("Done")
                self.wTree.get_widget("label_packages_done_value").set_label(_("Your software selection was backed up succesfully"))
                img = self.iconTheme.load_icon("dialog-information", 48, 0)
                self.wTree.get_widget("image_packages_done").set_from_pixbuf(img)
                self.wTree.get_widget("notebook1").next_page()
                gtk.gdk.threads_leave()
        gtk.gdk.threads_enter()
        self.wTree.get_widget("button_apply").hide()
        self.wTree.get_widget("button_back").hide()
        gtk.gdk.threads_leave()
        self.operating = False

    ''' check validity of file'''
    def load_package_list_cb(self, w):
        self.package_source = w.get_filename()
        # magic info, i.e. we ignore files that don't have this.
        try:
            source = open(self.package_source, "r")
            re = source.readlines()
            error = False
            for line in re:                
                line = line.rstrip("\r\n")
                if (line != ""):
                    if(not line.endswith("\tinstall")):                        
                        error = True
                        break
            source.close()
            if(error):
                MessageDialog(_("Backup Tool"), _("The specified file is not a valid software selection"), gtk.MESSAGE_ERROR).show()
                #self.wTree.get_widget("scroller_packages").hide()
                self.wTree.get_widget("button_forward").set_sensitive(False)
                return
            else:
                self.wTree.get_widget("button_forward").set_sensitive(True)
        except Exception, detail:
            print detail
            MessageDialog(_("Backup Tool"), _("An error occurred while accessing the file"), gtk.MESSAGE_ERROR).show()

	#################################################################################################################
    # xgm: check validity of file for restore system
    def load_file_for_restore_system(self, w):
        self.system_source = w.get_filename()
        self.restore_archive = True
        nfsfile = None
        self.tar = None
        try:
            if(self.restore_archive == True):
                if(not tarfile.is_tarfile(self.system_source)):
                    self.wTree.get_widget("button_forward").set_sensitive(False) 
                    MessageDialog(_("Backup Tool"), _("This is not a archive(tar) file."), gtk.MESSAGE_ERROR).show()
                    return False
	    		#此处判断文件格式类型
        except Exception, detail:
            #if(nfsfile is None):
            MessageDialog(_("Backup Tool"), _("This is not nfsbackup file."), gtk.MESSAGE_ERROR).show()
            return

        self.wTree.get_widget("button_forward").set_sensitive(True) 



    def update_restore_system_progress(self, current, total, message=None):
        current = float(current)
        total = float(total)
        fraction = float(current / total)
        gtk.gdk.threads_enter()
        self.wTree.get_widget("progressbar4").set_fraction(fraction)
        if(message is not None):
            self.wTree.get_widget("progressbar4").set_text(message)
        else:
            self.wTree.get_widget("progressbar4").set_text(str(int(fraction *100)) + "%")
        gtk.gdk.threads_leave()

    # xgm 判断目录所在分区
    def partation_of_dir(self, dir=None):
            if (not len(dir)):
                    return 
            dirInfo = ""
            tmp = commands.getoutput("df -h /boot/ | grep by-uuid")
            if(len(tmp)) :
                    command = "df -h /boot/ | grep by-uuid | \
                            awk -F'/' '{print $5}' | awk '{print $1}'"
                    uuidInfo = "/dev/disk/by-uuid/" + commands.getoutput(command)
                    dirInfo = os.readlink(uuidInfo).replace("../../", "/dev/")
            else:
                    command = "df -h /boot/ | grep /dev | awk -F' ' '{print $1}'"
                    dirInfo = commands.getoutput(command)
            return dirInfo
            
    # xgm 修复grub
    def repair_grub(self):
            boot_in_dev = self.partation_of_dir(self.boot_install_dir)
            grub_install = "grub-install %s" % (boot_in_dev[:len(boot_in_dev)-1])
            grub_mkconfig = "grub-mkconfig -o %s" % (self.boot_cfg)
            command = grub_install + " & " + grub_mkconfig
            os.system(command)

    def get_open_files(self): 
        path=[];
        x = [];
        x = "[" + commands.getoutput("lsof 2> /dev/null |awk 'NR>1' |awk '{print $9}'") + "]"
        x = re.sub('\n+', ',', str(x))
        x = x.split(",", x.count(","))
        return set(x)

    # xgm 恢复系统文件，从tar.gz
    def restore_system(self):
        tar_path = self.system_source
        target_path = self.system_dest_dir

        gtk.gdk.threads_enter()
        self.operating = True
        self.system_restore_stat = True
        gtk.gdk.threads_leave()

        self.update_restore_system_progress(0, 1, message=None)
        self.wTree.get_widget("progressbar4").show()

        error = None
        current = 0
        try:
            self.log.logger.info("Using file " + tar_path + " recovery system.")
            tar = tarfile.open(tar_path, "r:gz")
            self.wTree.get_widget("label_current_file_value3").set_text(_("Reading file. Just a minute, please."))
            file_names = tar.getnames()
            total = len(file_names)
            open_files = self.get_open_files()

            for file_name in file_names:
                try:
                    if(not self.operating):
                        self.operating = False
                        self.system_restore_stat = False
                        return
                    if "/"+file_name in open_files:
                        outstr = "[In use] Skip " + file_name 
                        self.log.nfs_info(outstr)
                        #self.wTree.get_widget("label_current_file_value3").set_text(outstr)
                        current += 1
                        continue

                    self.wTree.get_widget("label_current_file_value3").set_text(file_name)
                    tar.extract(file_name, target_path)
                    current += 1
                    self.update_restore_system_progress(current, total, message=None)
                except:
                    current += 1
                    self.log.nfs_error(traceback.format_exc() + _("Skip file \'") + file_name + _("\' and continue."))
                    #在界面显示异常
        except Exception, detail:
            self.log.nfs_error(traceback.format_exc() + _("####### recovery system failed. ######"))
        finally:
            tar.close()
            commands.getoutput('sync')
            f_cache = open('/proc/sys/vm/drop_caches', 'w')
            f_cache.write('3');
            f_cache.close()

        self.wTree.get_widget("label_current_file_value3").set_text(_("Being repaired grub ..."))
        self.repair_grub()
        self.wTree.get_widget("button_cancel").set_sensitive(True)

        self.wTree.get_widget("label_current_file_value3").set_text(_("Restore system success."))
        #self.wTree.get_widget("label_caption_copying3").show()
        if(error is not None):
            self.wTree.get_widget("label_caption_copying3").set_text(error)
        else:
            self.wTree.get_widget("label_caption_copying3").set_text(_("No error report."))

        gtk.gdk.threads_enter()
        self.operating = False
        self.system_restore_stat = False
        gtk.gdk.threads_leave()

##############################################################################################################

    ''' load package list into treeview '''
    def load_package_list(self):
        gtk.gdk.threads_enter()
        self.wTree.get_widget("button_forward").hide()
        self.wTree.get_widget("button_apply").show()
        self.wTree.get_widget("button_apply").set_sensitive(True)
        self.wTree.get_widget("main_window").set_sensitive(False)
        self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        model = gtk.ListStore(bool,str,bool,str)
        self.wTree.get_widget("treeview_package_list").set_model(model)
        gtk.gdk.threads_leave()
        try:
            source = open(self.package_source, "r")
            cache = apt.Cache()
            for line in source.readlines():
                if(line.startswith("#")):
                    # ignore comments
                    continue
                line = line.rstrip("\r\n")
                if(line == ""):
                    # ignore empty lines
                    continue
                line = line.split("\t")[0]
                inst = True
                if(cache.has_key(line)):
                    pkg = cache[line]
                    if(not pkg.is_installed):
                        desc = pkg.candidate.summary.replace("&", "&amp;")
                        line = "<big>" + line + "</big>\n<small>" + desc + "</small>"
                        gtk.gdk.threads_enter()
                        model.append([inst, line, inst, pkg.name])
                        gtk.gdk.threads_leave()
                else:
                    inst = False
                    line = "<big>" + line + "</big>\n<small>" + _("Could not locate the package") + "</small>"
                    gtk.gdk.threads_enter()
                    model.append([inst, line, inst, line])
                    gtk.gdk.threads_leave()
            source.close()
        except Exception, detail:
            print detail
            MessageDialog(_("Backup Tool"), _("An error occurred while accessing the file"), gtk.MESSAGE_ERROR).show()
        gtk.gdk.threads_enter()
        self.wTree.get_widget("main_window").set_sensitive(True)
        self.wTree.get_widget("main_window").window.set_cursor(None)
        if(len(model) == 0):
            self.wTree.get_widget("button_forward").hide()
            self.wTree.get_widget("button_back").hide()
            self.wTree.get_widget("button_apply").hide()
            self.wTree.get_widget("notebook1").set_current_page(16)
        else:
            self.wTree.get_widget("notebook1").set_current_page(15)
            self.wTree.get_widget("button_forward").set_sensitive(True)
        gtk.gdk.threads_leave()

    ''' Installs the package selection '''
    def install_packages(self):
        # launch synaptic..
        gtk.gdk.threads_enter()
        self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        self.wTree.get_widget("main_window").set_sensitive(False)
        gtk.gdk.threads_leave()

        cmd = ["sudo", "/usr/sbin/synaptic", "--hide-main-window", "--non-interactive", "--parent-window-id", str(self.wTree.get_widget("main_window").window.xid)]
        cmd.append("--progress-str")
        cmd.append("\"" + _("Please wait, this can take some time") + "\"")
        cmd.append("--finish-str")
        cmd.append("\"" + _("The installation is complete") + "\"")
        f = tempfile.NamedTemporaryFile()
        model = self.wTree.get_widget("treeview_package_list").get_model()
        for row in model:
            if(row[0]):
                f.write("%s\tinstall\n" % row[3])
        cmd.append("--set-selections-file")
        cmd.append("%s" % f.name)
        f.flush()
        comnd = subprocess.Popen(' '.join(cmd), shell=True)
        returnCode = comnd.wait()
        f.close()

        gtk.gdk.threads_enter()
        self.wTree.get_widget("main_window").window.set_cursor(None)
        self.wTree.get_widget("main_window").set_sensitive(True)
        self.wTree.get_widget("button_back").set_sensitive(True)
        self.wTree.get_widget("button_forward").set_sensitive(True)
        gtk.gdk.threads_leave()


        self.refresh(None)
    ''' select/deselect all '''
    def set_selection(self, w, treeview, selection, check):
        model = treeview.get_model()
        for row in model:
            if(check):
                if row[2]:
                    row[0] = selection
            else:
                row[0] = selection

    ''' refresh package selection '''
    def refresh(self, w):
        # refresh package list
        thr = threading.Thread(group=None, name="NFSBackup-packages", target=self.load_package_list, args=(), kwargs={})
        thr.start()

if __name__ == "__main__":
    gtk.gdk.threads_init()
    MintBackup()
    gtk.main()
