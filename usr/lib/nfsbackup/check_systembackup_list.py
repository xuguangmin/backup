#!/bin/env python
import os

def check_list():

    try:
        if not os.path.exists("/usr/lib/nfsbackup/systembackup_list"):
            return
        fd = open("/usr/lib/nfsbackup/systembackup_list", "r+")
        list = fd.readlines()
        fd.truncate(0)
        fd.seek(0)
        print list
        lines = list
        print lines
        count = len(list)
        print count
        for i in range(count):
            print i
            fullpath = "/"+list[i][0:-1]
            print fullpath
            if not os.path.exists(fullpath):
                print "remove"
                new_string = fullpath[1:len(fullpath)] + "\n"
                print new_string
                lines.remove(new_string)
        print lines   
        fd.writelines(lines)
        fd.close()

    except Exception, detail:
        print detail


if __name__ == "__main__":
    check_list()
