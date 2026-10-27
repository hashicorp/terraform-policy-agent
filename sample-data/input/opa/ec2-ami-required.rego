# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MPL-2.0

package terraform.ec2_ami_required

import input.plan as plan

# METADATA
# title: EC2 AMI Required
# description: EC2 instances must explicitly define an AMI
# custom:
#  enforcement_level: mandatory

rule[outcome] {
	r := plan.resource_changes[_]
	r.type == "aws_instance"
	r.change.after.ami == null

	meta := rego.metadata.chain()

	outcome := {
		"policy_name": rego.metadata.rule().title,
		"description": rego.metadata.rule().description,
		"enforcement_level": rego.metadata.rule().custom.enforcement_level,
		"output": sprintf("%-40s :: EC2 instance AMI is not explicitly defined",
			                    [r.address])
	}
}