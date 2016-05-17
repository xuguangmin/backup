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
    

    def backup_system(self):
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
                
                   for root,dir,files in os.walk(list1[i]):
                      
		      for file in files:
                        
                        fullpath = os.path.join(root,file)                    
			dir = os.path.split(fullpath)
                        #print fullpath
                        if dir[0] == self.system_dest:
                             #print dir[0]
                             continue
                        tar.add(fullpath)
                for i in range(len(list2)):
                    tar.add(list2[i])

	        tar.close()
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

if __name__ == "__main__":
    directory = NfsBackup()
    directory.backup_system()
