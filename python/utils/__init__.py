from subprocess import PIPE, Popen, call
import os
import jinja2

def runCommand(cmd):
	#cmd = cmd.split(' ')
	process = Popen(cmd, stderr=PIPE, stdout=PIPE, shell=True)
	stdout, stderr = process.communicate()
	rt = process.returncode

	return stdout, stderr, rt

class CommandException(Exception):
	pass

#
# log_file only when interactive is set to True
#
class Command(object):
	def __init__(self, dry=False, interactive=None, log_file=None):
		self._dry = dry
		self._so = ""
		self._se = ""
		self._rc = 0
		self._interactive = interactive
		self._log_file = log_file

	def run(self, cmd, interactive=False, error=""):
		if self._dry:
			print("Would have run: %s" % cmd)
			return self

		if self._interactive != None:
			interactive = self._interactive

		if interactive:
			if call(cmd, shell=True, stdout=self._log_file, stderr=self._log_file) > 0:
				if error == "":
					raise CommandException("'%s' failed" % cmd)
				else:
					raise CommandException("'%s' failed: %s" % (cmd, error))
			return self

		self._so, self._se, self._rc = runCommand(cmd)

		return self

	def out(self):
		return "\n".join(self._so.split("\n")[:-1])

	def rc(self):
		return self._rc

	def err(self):
		return self._se

def isFedora():
	with open("/etc/redhat-release", "r") as f:
		for line in f.read().split("\n"):
			if "Fedora" in line:
				return True

	return False

def getScriptDir(file=__file__):
        return os.path.dirname(os.path.realpath(file))

def renderTemplate(searchpath, template_file, template_vars):

	templateLoader = jinja2.FileSystemLoader( searchpath=searchpath )
	templateEnv = jinja2.Environment( loader=templateLoader )
	template = templateEnv.get_template( template_file )
	content = template.render( template_vars )

	return content
