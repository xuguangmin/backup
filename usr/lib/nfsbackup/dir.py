#!/usr/bin/env python

try:
    import pygtk
    pygtk.require("3.0")
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


''' The main class of the app '''
class NfsBackup:

    ''' New NfsBackup '''
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
        self.description = "nfsBackup"
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

        # Copy to other directory, possibly on another device
        for f in filelist:
            os.chdir(f[0])
            rpath = os.path.join(f[0],f[1])                
            path = os.path.relpath(rpath)
            target = os.path.join(self.backup_dest, path)
            if(os.path.islink(rpath)):
                if(self.follow_links):
                    if(not os.path.exists(rpath)):
                        current_file += 1
                        continue
                else:
                    current_file += 1
                    continue
            dir = os.path.split(target)
            if(not os.path.exists(dir[0])):
                try:
                    os.makedirs(dir[0])
                except Exception, detail:
                    print detail
                    self.errors.append([dir[0], str(detail)])
            try:
                if(os.path.exists(target)):
                    #always overwrite
                    os.remove(target)
                    self.copy_file(rpath, target, sourceChecksum=None)
                else:
                    self.copy_file(rpath, target, sourceChecksum=None)
                current_file = current_file + 1
            except Exception, detail:
                print detail
                self.errors.append([rpath, str(detail)])
            del f
        for row in self.backup_sour:
            new_row=os.path.split(row)
            if(os.path.isdir(row)):
                os.chdir(new_row[0])
                if(self.preserve_times or self.preserve_perms):
                    #the directorie now to reset the a/m/time
                    path = os.path.relpath(row)
                    target = os.path.join(self.backup_dest, path)
                    self.clone_dir(row, target)
                for top,dirs,files in os.walk(top=row,onerror=None, followlinks=self.follow_links):
                    if(self.preserve_times or self.preserve_perms):
                        # loop back over the directories now to reset the a/m/time
                        for d in dirs:
                            rpath = os.path.join(top, d)
                            path = os.path.relpath(rpath)
                            target = os.path.join(self.backup_dest, path)
                            self.clone_dir(rpath, target)
                            del d

        if(current_file < total):
            self.errors.append([_("Warning: Some files were not saved, copied: %(current_file)d files out of %(total)d total") % {'current_file':current_file, 'total':total}, None])
        if(len(self.errors) > 0):
            print self.errors
        else:
            print "The backup completed successfully"

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
                read = src.read(BUF_MAX)
                if(read):
                    dst.write(read)
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
                    os.fchown(fd, owner, group)
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
                    file1 = ''
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
                read = input.read(MAX_BUF)
                if(not read):
                    break
                check.update(read)
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
                read = source.read(MAX_BUF)
                if(not read):
                    break
                check.update(read)
            source.close()
            return check.hexdigest()
        except Exception, detail:
            self.errors.append([source, str(detail)])
            print detail
        return None

directory = NfsBackup()
directory.backup()
