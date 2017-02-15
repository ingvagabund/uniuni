import yaml
import os
import logging

from utils import Command, CommandException, renderTemplate
# TODO(jchaloup): this needs to be changes to kubernetesci.core.... import
from core.results.uploader import GSBucketUploader
from core.results.notifier import GithubNotifier
from core.errors import TestStatus, ERROR, FAILURE, SUCCESS

class ClusterCapacityPRCI(object):

	"""Run cluster capacity tests over Kubernetes cluster
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
		try:
			uploader.upload()
		except CommandException as e:
			logging.error("Unable to upload results: %s" % e)

	def notifyResults(self, status):
		n = GithubNotifier(
			self._config_data["results_notifier"]["project"],
			self._config_data["results_notifier"]["issue"],
			self._config_data["results_notifier"]["sha"],
			self._config_data["results_notifier"]["context"],
			self._config_data["results_notifier"]["token"],
			self._config_data["results_notifier"]["internal_target_url"],
			self._config_data["results_notifier"]["trigger_phrase"]
		)
		n.registerStatus(ERROR, self._config_data["results_notifier"]["pr_status"]["error_msg"], self._config_data["results_notifier"]["pr_comment"]["error_msg"])
		n.registerStatus(FAILURE, self._config_data["results_notifier"]["pr_status"]["failure_msg"], self._config_data["results_notifier"]["pr_comment"]["failure_msg"])
		n.registerStatus(SUCCESS, self._config_data["results_notifier"]["pr_status"]["success_msg"], self._config_data["results_notifier"]["pr_comment"]["success_msg"])

		n.notify(status=status, update_pr_status=self._config_data["results_notifier"]["pr_status"]["enabled"], comment_pr=self._config_data["results_notifier"]["pr_comment"]["enabled"])

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

		os.chdir(self._config_data["general"]["cluster_capacity_dir"])

		ts = TestStatus()

		#build CC
		try:
			self._command.run("make")
		except CommandException as e:
			logging.error(e)
			ts.update(ERROR)

		#Run unit-tests
		if self._config_data["tests"]["unit_tests"]["enabled"]:
			try:
				self._command.run("make test")
			except CommandException as e:
				logging.error(e)
				ts.update(ERROR)

		# Run integration tests
		if self._config_data["tests"]["integration_tests"]["enabled"]:
			os.environ["KUBE_CONFIG"] = str(self._config_data["kubernetes"]["kubeconfig"])
			try:
				self._command.run("make integration-tests")
			except CommandException as e:
				logging.error(e)
				ts.update(ERROR)

		# upload logs to GS Bucket
		if self._config_data["results_uploader"]["enabled"]:
			self.uploadResults()

		# comment GH PR
		if self._config_data["results_notifier"]["enabled"]:
			self.notifyResults(ts.status())

if __name__ == "__main__":
	config_vars = {
		"issue_id": 37,
		"issue_commit": "0b1196ceda140c0c2bff4663a0519fde2ab05a3f",
		"build_id": 1,
		"kubeconfig": "/home/jchaloup/Projects/uniuni/kubeconfig",
		"results_dir": "/home/jchaloup/Projects/uniuni/artifacts",
		"cluster_capacity_dir": "/home/jchaloup/Projects/src/github.com/kubernetes-incubator/cluster-capacity",
	}
	o = ClusterCapacityPRCI(config_vars=config_vars, dry_run=False)
	o.run()
