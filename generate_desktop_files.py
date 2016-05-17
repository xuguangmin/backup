#!/usr/bin/python

import commands, os

sourceFile = "usr/lib/nfsbackup/nfsBackup.py"

menuName = commands.getoutput("cat " + sourceFile + " | grep menuName")
menuName = menuName.replace("menuName", "")
menuName = menuName.replace("=", "")
menuName = menuName.replace("_(", "")
menuName = menuName.replace("\"", "")
menuName = menuName.replace(")", "")
menuName = menuName.strip()

menuComment = commands.getoutput("cat " + sourceFile + " | grep menuComment")
menuComment = menuComment.replace("menuComment", "")
menuComment = menuComment.replace("=", "")
menuComment = menuComment.replace("_(", "")
menuComment = menuComment.replace("\"", "")
menuComment = menuComment.replace(")", "")
menuComment = menuComment.strip()

desktopFile = open("usr/share/applications/nfsBackup.desktop", "w")
desktopFile2 = open("usr/share/applications/nfsBackup_mime.desktop", "w")
desktopFile.writelines("""[Desktop Entry]
Name=Backup Tool
""")
desktopFile2.writelines("""[Desktop Entry]
Name=Backup Tool
""")

import gettext
gettext.install("nfsbackup", "/usr/share/nfsbackup/locale")

for directory in os.listdir("/usr/share/nfsbackup/locale"):
	if os.path.isdir(os.path.join("/usr/share/nfsbackup/locale", directory)):
		try:
			language = gettext.translation('nfsbackup', "/usr/share/nfsbackup/locale", languages=[directory])
			language.install()
			desktopFile.writelines("Name[%s]=%s\n" % (directory, _(menuName)))
			desktopFile2.writelines("Name[%s]=%s\n" % (directory, _(menuName)))
		except:
			pass

desktopFile.writelines("Comment=Make a backup of your home directory\n")
desktopFile2.writelines("Comment=Make a backup of your home directory\n")

for directory in os.listdir("/usr/share/nfsbackup/locale"):
	if os.path.isdir(os.path.join("/usr/share/nfsbackup/locale", directory)):
		try:
			language = gettext.translation('nfsbackup', "/usr/share/nfsbackup/locale", languages=[directory])
			language.install()			
			desktopFile.writelines("Comment[%s]=%s\n" % (directory, _(menuComment)))
			desktopFile2.writelines("Comment[%s]=%s\n" % (directory, _(menuComment)))
		except:
			pass

desktopFile.writelines("""Exec=nfsbackup
Icon=/usr/lib/nfsbackup/icon.svg
Terminal=false
Type=Application
Encoding=UTF-8
Categories=System;
""")
desktopFile2.writelines("""Exec=nfsBackup
Icon=/usr/lib/nfsbackup/icon.png
Terminal=false
Type=Application
Encoding=UTF-8
Categories=Application;System;Settings
NoDisplay=true
MimeType=application/x-backup;
""")

