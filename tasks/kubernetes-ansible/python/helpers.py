from utils import Command, CommandException, getScriptDir, isFedora
import json
import os

class RedHatKubernetesAnsibleDeployment(object):

	def __init__(self, ansible_dir, resource_file, cluster_os, kubeconfig_dest, private_key=None, log_file=None, dry=False):

		self._dry = dry
		self._class_dir = getScriptDir(__file__)
		self._ansible_dir = ansible_dir
		self._resource_file = resource_file
		self._kubeconfig_dest = kubeconfig_dest
		self._log_file = log_file
		self._private_key = private_key
		self._cluster_os = cluster_os

		inventory_dir = os.path.join(self._ansible_dir, "inventory")
		if "INVENTORY" in os.environ:
			self._inventory = os.environ["INVENTORY"]

		if "INVENTORY" not in os.environ:
			if os.path.exists(inventory_dir):
				self._inventory = os.path.join(self._ansible_dir, "inventory/central_ci_dynamic_hosts.py")
			else:
				self._inventory = os.path.join(self._class_dir, "central_ci_dynamic_hosts.py")

		self._playbooks_dir = os.path.join(self._class_dir, "playbook")

		data = json.load(open(resource_file))
		nodes = []
		masters = []

		for node in data["resources"]:
			nodes.append(node["ip"])
			if "masters" in node["metadata"]["ansible-group"]:
				masters.append(node["ip"])

		assert len(masters) > 0
		assert len(nodes) > 0

		self._cluster_resources = {}
		self._cluster_resources["nodes"] = nodes
		self._cluster_resources["masters"] = masters

		data

	def deployCluster(self, ansible_config, docker_from_brew=False):
		c = Command(self._dry, interactive=True, log_file=self._log_file)

		print("Deploying Kubernetes cluster")
		c.run("sudo yum install -y ansible")
		if "RESOURCE_FILE" not in os.environ:
			os.environ["RESOURCE_FILE"] = os.path.join(self._resource_file)

		# does inventory dir exist?
		inventory_dir = os.path.join(self._ansible_dir, "inventory")
		if os.path.exists(inventory_dir):
			c.run("cp %s/central_ci_dynamic_hosts.py %s/." % (self._class_dir, inventory_dir))
			if "GROUP_VARS_DIR" not in os.environ:
				os.environ["GROUP_VARS_DIR"] = inventory_dir
		else:
			if "GROUP_VARS_DIR" not in os.environ:
				os.environ["GROUP_VARS_DIR"] = self._ansible_dir

		c.run("echo \"--------------------------------------------------------------------------------\"")
		c.run("echo \"Pinging test resources: %s\"" % ",".join(self._cluster_resources["nodes"]))
		c.run("echo -n %s | xargs -I{} -d , ping -c 2 {}" % ",".join(self._cluster_resources["nodes"]), error="At least one existing node failed to respond")
		c.run("echo \"--------------------------------------------------------------------------------\"")
		c.run("echo \"--------------------------------------------------------------------------------\"")
		c.run("echo \"Setting and running ansible playbooks:\"")

		# Set ansible preferences
		os.environ["ANSIBLE_HOST_KEY_CHECKING"] = "False"
		os.environ["ANSIBLE_SCP_IF_SSH"] = "y"
		backdir = os.getcwd()
		os.chdir(self._ansible_dir)

		c.run("echo \"Tuning ansible script knobs before running...\"")
		# --extra-vars
		# open_cadvisor_port
		#   Open tcp/4194 port for cadvisor
		#
		# flannel_subnet, flannel_prefix
		#   This is required because the default flannel_subnet
		#   suggested will overlap with the QEOS subnet.
		#
		# source_type
		#   Deploy kubernetes build on the slave, not the one from distro repository
		#
		# kube_master_api_port
		#   We need to use a non-privileged port number so that the kube user
		#   will be able to bind to it when launching the apiserver
		#
		# kube_cert_ip
		#   We want the certificate to be valid for the public IP of the
		#   master, which will be retrieved from the OS metadata server
		#
		# kube_apiserver_insecure_bind_address
		#   We also have to make the apiserver listen unsafely on all
		#   interfaces so that we don't have to set up authentication for
		#   testing (alternatively, set up authentication)
		items = []
		for key in ansible_config:
			items.append("%s=%s" % (key, ansible_config[key]))

		extra_vars = " ".join(items)

		c.run("echo \"Setting extra vars: %s\"" % extra_vars)

		# update to the latest systemd otherwise libselinux conflicts with it
		c.run("sudo yum update -y systemd")
		# python-selinux has to be installed on slave
		c.run("sudo yum install -y libselinux-python")

		if self._private_key:
			os.environ["ANSIBLE_PRIVATE_KEY_FILE"] = self._private_key

		if self._cluster_os == "fedora":
			c.run("echo \"Running fedora bootstraping\"")
			c.run("ansible-playbook -i %s %s/kube_github_preload/bootstrap-fedora.yml" % (self._inventory, self._playbooks_dir), error="kubernetes cluster playbook failed")

		c.run("echo \"Running install prerequirements playbook...\"")
		c.run("ansible-playbook -i %s %s/kube_github_preload/main.yml" % (self._inventory, self._playbooks_dir), error="kubernetes cluster playbook failed")

		# hack tasks/docker/... playbook to install the latest docker from brew
		if docker_from_brew:
			c.run("echo \"Updating docker task for install latest docker from brew\"")
			c.run("cp %s/docker_custom_install/brew-latest-install.ansible roles/docker/tasks/brew-latest-install.yml" % self._playbooks_dir)
			c.run("sed -i \"s/^- include: generic-install.yml/- include: brew-latest-install.yml/\" roles/docker/tasks/main.yml")

		# setup.sh is part of the kubernetes/contrib repository
		c.run("echo \"Running kubernetes playbook...\"")
		if os.path.exists("./setup.sh"):
			c.run("INVENTORY=%s ANSIBLE_SSH_ARGS='-o ControlMaster=no' ./setup.sh --extra-vars \"%s\"" % (self._inventory, extra_vars), error="kubernetes cluster playbook failed")
		else:
			os.chdir("scripts")
			c.run("INVENTORY=%s ANSIBLE_SSH_ARGS='-o ControlMaster=no' ./deploy-cluster.sh --extra-vars \"%s\"" % (self._inventory, extra_vars), error="kubernetes cluster playbook failed")

		# Retrieve the kubeconfig file for use with upcoming e2e run
		c.run("echo \"Retrieve kubeconfig from the master...\"")
		# must be set to n, otherwise fetch fails (don't know why)
		os.environ["ANSIBLE_SCP_IF_SSH"] = "n"
		c.run("ansible-playbook -i %s %s/kube_github_preload/kubeconfig.yml --extra-vars=\"kubeconfig_dest=%s\"" % (self._inventory, self._playbooks_dir, self._kubeconfig_dest), error="kubernetes cluster playbook failed")

		os.chdir(backdir)
