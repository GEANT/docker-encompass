## enCompass

### Intro

enCompass is a Puppet External Nodes classifier.

VM configurations and statuses are stored in a hierarchical folder structure.

Status files inside the folders are handled by Terraform.

### Folder Structure

- **1st level**: application name  
- **2nd level**: datacenter location (lon, fra, par…)  
- **3rd level**: environment (test, uat, prod)  
- Last level: variables.tf.json, nsx_tags.json, etc.

### Authentication

Authentication is configured against the Windows Domain GEANT.LOCAL.

Users should be added to proper groups on the domain controller.

Use only the username (name.surname) without the domain.

### NSX-T tags

- Multiple tags can be selected  
- Tags apply to all VMs in the same folder  
- At least one tag must be selected
