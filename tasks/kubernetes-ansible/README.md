# Unit unit for upstream kubernetes ansible PRs

## Supported OSes

* RHEL
* Fedora
* CentOS

## Current solution

Deployment of kubernetes (master + PR branch) via Vagrant.
By default, package based deployment is tested.
Based on an OS, different set of default values is overwriten.

RHEL: ``kube_source_type=packageManager``
Fedora:  ``kube_source_type=packageManager``
CentOS: ``kube_source_type=github-release``, ``kube_master_api_port=6443`` 
