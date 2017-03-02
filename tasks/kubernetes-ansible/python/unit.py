from utils import Command, CommandException, getScriptDir, renderTemplate
import yaml
import os
# TODO(jchaloup): this needs to be changes to kubernetesci.core.... import
from core.results.uploader import GSBucketUploader
from core.results.notifier import GithubNotifier
from core.errors import TestStatus, ERROR, FAILURE, SUCCESS
import logging
from helpers import RedHatKubernetesAnsibleDeployment

# Requirements:
# - kubernetes ansible + Vagrantfile
# - ANSIBLE_EXTRA_VARS (optional)
#

class KubernetesAnsibleDeploymentCI(object):

	"""Deploy kubernetes cluster via Vagrantfile or over a cluster
	param ansible_dir: directory with ansible playbooks and Vagrantfile for Kubernetes deployment
	type  ansible_dir: directory
	"""
	def __init__(self,
			config=None,
			config_vars=None,
			dry_run=False
		):

		self._dry_run = dry_run
		if not config:
			config = "%s/../config.yaml" % getScriptDir(__file__)

		if config_vars:
			self._config_data = yaml.load(renderTemplate(os.path.dirname(config), os.path.basename(config), config_vars))
		else:
			self._config_data = yaml.load(open(config, 'r'))

	def uploadResults(self):
		uploader = GSBucketUploader(
			self._config_data["general"]["results_dir"],
			self._config_data["results_uploader"]["target_url"],
			self._config_data["results_uploader"]["internal_target_url"],
			self._config_data["results_uploader"]["boto_config_file"],
			dry=self._dry_run
		)

		uploader.upload()

	def notifyResults(self, status):
		n = GithubNotifier(
			self._config_data["results_notifier"]["project"],
			self._config_data["results_notifier"]["issue"],
			self._config_data["results_notifier"]["sha"],
			self._config_data["results_notifier"]["context"],
			self._config_data["results_notifier"]["token"],
			self._config_data["results_notifier"]["target_url"],
			self._config_data["results_notifier"]["trigger_phrase"]
		)
		n.registerStatus(ERROR, self._config_data["results_notifier"]["pr_status"]["error_msg"], self._config_data["results_notifier"]["pr_comment"]["error_msg"])
		n.registerStatus(FAILURE, self._config_data["results_notifier"]["pr_status"]["failure_msg"], self._config_data["results_notifier"]["pr_comment"]["failure_msg"])
		n.registerStatus(SUCCESS, self._config_data["results_notifier"]["pr_status"]["success_msg"], self._config_data["results_notifier"]["pr_comment"]["success_msg"])

		n.notify(status=status, update_pr_status=self._config_data["results_notifier"]["pr_status"]["enabled"], comment_pr=self._config_data["results_notifier"]["pr_comment"]["enabled"])


	def runVagrantDeployment(self):
		# It is expected the ansible directory is completely set up and ready for use.
		# If needed, ANSIBLE_EXTRA_VARS can be used to set extra vars to set or override existing ansible variables.
		os.chdir("%s/vagrant" % self._config_data["general"]["ansible_dir"])

		# construct ansible extra vars
		if self._config_data["deployment"]["vagrant"]["ansible"] != None:
			pairs = []
			for key in self._config_data["deployment"]["vagrant"]["ansible"]:
				pairs.append("%s=%s" % (key, self._config_data["deployment"]["vagrant"]["ansible"][key]))
			os.environ["ANSIBLE_EXTRA_VARS"] = " ".join(pairs)
			print "ANSIBLE_EXTRA_VARS=\"%s\"" % os.environ["ANSIBLE_EXTRA_VARS"]

		# set image, number of nodes
		if self._config_data["deployment"]["vagrant"] != None:
			for key in self._config_data["deployment"]["vagrant"]:
				os.environ[ key.upper() ] = str(self._config_data["deployment"]["vagrant"][key])
				print "%s=\"%s\"" % (key.upper(), os.environ[ key.upper() ])

		# It is expected Vagrant technology is completely set up and ready for use.
		# If needed, OS_IMAGE and other envs can be set to alter provisioning.
		self._command.run("vagrant up")

		# collect kubeconfig from master node
		ssh_command = Command(dry=self._dry_run).run("sudo vagrant ssh-config")
		if ssh_command.rc() > 0:
			logging.error("Unable to retrieve vagrant ssh-config: %s" % ssh_command.err())
			exit(1)

		lines = ssh_command.out().split("\n")

		master_line = True
		vagrant_master_ip = ""
		for line in lines:
			if line.startswith("Host kube-master-1"):
				master_line=True
				continue

			if master_line and line.startswith("  HostName "):
				vagrant_master_ip = line.split("  HostName ")[1].strip()
				print vagrant_master_ip
				break

			if line == "":
				master_line=False

		self._command.run("scp -i ~/.vagrant.d/insecure_private_key -o StrictHostKeyChecking=no vagrant@%s:/etc/kubernetes/kubectl.kubeconfig %s" % (vagrant_master_ip, self._config_data["general"]["kubeconfig_dest_dir"]))

	def runOpenstackDeployment(self):
		o = RedHatKubernetesAnsibleDeployment(
				self._config_data["general"]["ansible_dir"],
				self._config_data["deployment"]["openstack"]["resources"],
				self._config_data["deployment"]["openstack"]["os"],
				self._config_data["general"]["kubeconfig_dest_dir"],
				self._config_data["deployment"]["openstack"]["private_key"],
				dry=self._dry_run
			)
		o.deployCluster(self._config_data["deployment"]["openstack"]["ansible"])

	def run(self):
		# Need a place to put all logs
		if not os.path.exists(self._config_data["general"]["results_dir"]):
			os.mkdir(self._config_data["general"]["results_dir"])

		log_file_fd = None
		if "log_file" in self._config_data["general"]:
			log_file = os.path.join(self._config_data["general"]["results_dir"], self._config_data["general"]["log_file"])
			print "Logs available in %s" % log_file
			log_file_fd = open(log_file, "w")

		self._command = Command(dry=self._dry_run, interactive=True, log_file=log_file_fd)

		# provision Kubernetes cluster via Vagrantfile
		# from https://github.com/kubernetes/contrib under
		# ansible/vagrant directory

		# Need a place to put all logs
		if not os.path.exists(self._config_data["general"]["results_dir"]):
			os.mkdir(self._config_data["general"]["results_dir"])

		if self._config_data["deployment"]["vagrant"]["enabled"]:
			self.runVagrantDeployment()
		elif self._config_data["deployment"]["openstack"]["enabled"]:
			self.runOpenstackDeployment()

		# collect logs
		os.chdir(self._config_data["general"]["results_dir"])

		# upload logs to GS Bucket
		if self._config_data["results_uploader"]["enabled"] and not self._config_data["results_uploader"]["skip_success"]:
			self.uploadResults()

		# comment GH PR
		if self._config_data["results_notifier"]["enabled"] and not self._config_data["results_notifier"]["skip_success"]:
			self.notifyResults(SUCCESS)

	def checked_run(self):
		"""Make sure any exception is catch and a PR is notified
		"""
		try:
			self.run()
		except:
			# upload logs to GS Bucket
			if self._config_data["results_uploader"]["enabled"]:
				self.uploadResults()

			# comment GH PR
			if self._config_data["results_notifier"]["enabled"]:
				self.notifyResults(FAILURE)


if __name__ == "__main__":
	config_vars = {
		"issue_id": 37,
		"issue_commit": "0b1196ceda140c0c2bff4663a0519fde2ab05a3f",
		"build_id": 1,
		"kubeconfig": "/home/jchaloup/Projects/uniuni/kubeconfig",
		"results_dir": "/home/jchaloup/Projects/uniuni/artifacts",
		"ansible_dir": "/home/jchaloup/Projects/src/github.com/kubernetes/contrib/ansible",
		"resources": "/home/jchaloup/Projects/uniuni/resources.json",
		"private_key": "/home/jchaloup/Projects/atomic-ci-jobs/project/config/keys/ci-factory",
	}
	o = KubernetesAnsibleDeploymentCI(config_vars=config_vars, dry_run=False)
	o.run()
