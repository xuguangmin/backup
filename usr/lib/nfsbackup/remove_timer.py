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
                print "usage: " + sys.argv[0] + " ... backup_destination"
                self.system_dest = sys.argv[1]
            else:
                sys.exit(1)
        else:
            print "usage: " + sys.argv[0] + " backup_destination"
            sys.exit(1)

    def system_remove(self):
        list =[]
        dir = self.system_dest
        if not os.path.isdir(dir):
            return
        try:
            if not os.path.exists("/usr/lib/nfsbackup/backup_system_stat"):
                return
            if not os.path.exists("/usr/lib/nfsbackup/systembackup_list"):
                return 
            fd = open("/usr/lib/nfsbackup/backup_system_stat", "r")
            line = fd.readline()
            stat_list = line.split(",")
            fd.close()
            if stat_list[1] == "using\n":
                return
            fd = open("/usr/lib/nfsbackup/systembackup_list", "r+")
            list = fd.readlines()
            fd.truncate(0)
            fd.seek(0)
 
            local_time = strftime("%Y-%m-%d", localtime())
            time_list =local_time.split("-")
      
            list.sort()
            lines = list
            count = len(list)  
            if count <= 1:
                return
            filetime=list[count-1].split("-")
            for i in range(count):
                fullpath = "/"+list[i][0:-1]
                new_filetime = list[i].split("-")
                if(time_list[0] == filetime[0]):
                    if(int(time_list[1])-int(filetime[1]) <= 1):
                        continue
                    if os.path.exists(fullpath):
                        cmd ="rm %s"%(fullpath)
                        os.system(cmd)
                    n = len(fullpath)
                    new_string = fullpath[1:n] + "\n"
                    lines.remove(new_string)
                else:
                    if i == count-1:
                        break
                    if os.path.exists(fullpath):
                        cmd ="rm %s"%(fullpath)
                        os.system(cmd)
                    n = len(fullpath)
                    new_string = fullpath[1:n] + "\n"
                    lines.remove(new_string)

            fd.writelines(lines)
            fd.close()
        except Exception, detail:
            print detail

if __name__ == "__main__":
    directory = NfsBackup()
    directory.system_remove()


