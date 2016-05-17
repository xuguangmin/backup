#!/usr/bin/env python

try:
    import pygtk
    pygtk.require("2.0")
except Exception, detail:
    print "You do not have a recent version of GTK"

try:
    import os
    import sys
    import commands
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
except Exception, detail:
    print "You do not have the required dependencies"


class TarFileMonitor():
    ''' Bit of a hack but I can figure out what tarfile is doing now.. (progress wise) '''
    def __init__(self, target):
        self.counter = 0
        self.size = 0
        self.f = open(target, "rb")
        self.name = self.f.name
        self.fileno = self.f.fileno
        self.size = os.path.getsize(target)
    def read(self, size=None):
        bytes = 0
        if(size is not None):
            bytes = self.f.read(size)
            if(bytes):
                self.counter += len(bytes)
        else:
            bytes = self.f.read()
            if(bytes is not None):
                self.counter += len(bytes)
        return bytes
    def close(self):
        self.f.close()

''' The main class of the app '''
class NfsBackup:

    ''' New NFSBackup '''
    def __init__(self):
        # handle command line filenames
        if(len(sys.argv) > 1):
            if(len(sys.argv) == 2):
                print "usage: " + sys.argv[0] + " backup_source1 backup_source2 ... backup_destination"
                sys.exit(1)
            else:
                self.backup_sour = sys.argv[1:-1]
                self.backup_dest = sys.argv[-1]
        else:
            print "usage: " + sys.argv[0] + " backup_source1 backup_source2 ... backup_destination"
            sys.exit(1)
        # preserve permissions?
        self.preserve_perms = True
        # preserve times?
        self.preserve_times = True
        # post-check files?
        self.postcheck = True
        # follow symlinks?
        self.follow_links = False
        # error?
        self.errors = []
        # tarfile
        self.tar = True


    ''' Creates a .nfsbackup file (for later restoration) '''
    def create_backup_file(self):
        self.description = "NFSBackup"
        try:
            of = os.path.join(self.backup_dest, ".nfsbackup")
            out = open(of, "w")
            lines = [  "source: %s\n" % (self.backup_dest),
                                    "file_count: %s\n" % (self.file_count),
                                    "description: %s\n" % (self.description) ]
            out.writelines(lines)
            out.close()
        except:
            return False
        return True

    ''' Does the actual copying '''
    def backup(self):
        filelist = []
        # get a count of all the files
        total = 0
        
        for row in self.backup_sour:
            new_row=os.path.split(row)
            if(os.path.isfile(row)):
                total += 1
                filelist.append(new_row)
            else:
                os.chdir(new_row[0])
                for top,dirs,files in os.walk(top=row,onerror=None, followlinks=self.follow_links):
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

        tar = None
        filetime = strftime("%Y-%m-%d-%H%M-backup", localtime())
        filename = os.path.join(self.backup_dest, filetime + ".tar.part")
        final_filename = os.path.join(self.backup_dest, filetime + ".tar")
        try:
            tar = tarfile.open(name=filename, dereference=self.follow_links, mode="w", bufsize=1024)
            nfsfile = os.path.join(self.backup_dest, ".nfsbackup")
            tar.add(nfsfile, arcname=".nfsbackup", recursive=False, exclude=None)
        except Exception, detail:
            print detail
            self.errors.append([str(detail), None])
        #backup sources
        for f in filelist:
            os.chdir(f[0])
            rpath = os.path.join(f[0],f[1])
            path = os.path.relpath(rpath)
            target = os.path.join(self.backup_dest, path)
            if(os.path.islink(rpath)):
                if(self.follow_links):
                    if(not os.path.exists(rpath)):
                        self.errors.append([rpath, _("Broken link")])
                        continue
                else:
                    current_file += 1
                    continue
            try:
                underfile = TarFileMonitor(rpath)
                finfo = tar.gettarinfo(name=None, arcname=path, fileobj=underfile)
                tar.addfile(fileobj=underfile, tarinfo=finfo)
                underfile.close()
            except Exception, detail:
                print detail
                self.errors.append([rpath, str(detail)])
            current_file = current_file + 1
        for row in self.backup_sour:
            new_row=os.path.split(row)
            if(os.path.isdir(row)):
                os.chdir(new_row[0])
                for top,dirs,files in os.walk(top=row,onerror=None, followlinks=self.follow_links):
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

        if(current_file < total):
            self.errors.append([_("Warning: Some files were not saved, copied: %(current_file)d files out of %(total)d total") % {'current_file':current_file, 'total':total}, None])
        if(len(self.errors) > 0):
            print self.errors
        else:
            print "The backup completed successfully"
        self.operating = False
tar = NfsBackup()
tar.backup()
