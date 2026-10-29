# Writes catalog/google-cloud-* (rules and fixtures) from Google API
# discovery documents. Run from the repo root:
#   python3 -I gcpgen.py <folder with the discovery JSON files>
import json, os, re, sys

SRC_DIR = sys.argv[1]
DISCOVERY_DIR = "https://www.googleapis.com/discovery/v1/apis/{api}/{version}/rest"
# Versions the directory does not list are served by the API's own host.
DISCOVERY_OWN = {("iam", "v2"): "https://iam.googleapis.com/$discovery/rest?version=v2",
                 ("run", "v2"): "https://run.googleapis.com/$discovery/rest?version=v2",
                 ("cloudfunctions", "v2"): "https://cloudfunctions.googleapis.com/$discovery/rest?version=v2"}

class _D:
    @staticmethod
    def format(api, version):
        return DISCOVERY_OWN.get((api, version), DISCOVERY_DIR.format(api=api, version=version))

DISCOVERY = _D()

def load(api, version):
    return json.load(open(os.path.join(SRC_DIR, f"{api}_{version}.json")))

PUBLIC_ACL = '"(?i)^(publicRead|publicReadWrite|authenticatedRead|bucketOwnerRead)$"'

# ---------------------------------------------------------------- Cloud SQL
SQL = {
    "Backups.CreateBackup": ("write", None),
    "Backups.DeleteBackup": ("irreversible", "A deleted backup cannot be restored from."),
    "Backups.UpdateBackup": ("write", None),
    "backupRuns.delete": ("irreversible", "A deleted backup cannot be restored from."),
    "backupRuns.insert": ("write", None),
    "blueGreenDeployments.create": ("money", "Creates a green copy of the instance, which is billed."),
    "blueGreenDeployments.delete": ("delete", "The green instance holds a copy of the blue one's data."),
    "blueGreenDeployments.switchover": ("write", "Points production at the green instance."),
    "connect.generateEphemeral": ("credential", "Returns a client certificate that lets its holder connect to the instance."),
    "databases.delete": ("irreversible", "Drops the database with its data."),
    "databases.insert": ("write", None),
    "databases.patch": ("write", None),
    "databases.update": ("write", None),
    "instances.RotateEntraIdCertificate": ("access", "Changes the certificates clients trust when connecting."),
    "instances.RotateServerCertificate": ("access", "Changes the certificates clients trust when connecting."),
    "instances.acquireSsrsLease": ("write", None),
    "instances.addEntraIdCertificate": ("access", "Changes the certificates clients trust when connecting."),
    "instances.addServerCa": ("access", "Changes the certificates clients trust when connecting."),
    "instances.addServerCertificate": ("access", "Changes the certificates clients trust when connecting."),
    "instances.clone": ("money", "Creates a new instance, which is billed."),
    "instances.delete": ("irreversible", "Deletes the instance, its databases and its automated backups. A final backup is kept only when the request asks for one, and a rule cannot make a call looser for an argument, so the delete counts as irreversible."),
    "instances.demote": ("irreversible", "Makes the instance a replica of an external database, which replaces its data."),
    "instances.demoteMaster": ("irreversible", "Makes the instance a replica of an external database, which replaces its data."),
    "instances.executeSql": ("unknown", "The class comes from the SQL, read as both Postgres and MySQL since Opfence cannot tell the instance's engine; SQL Server's T-SQL is unknown."),
    "instances.export": ("access", "Writes the instance's data to the Cloud Storage location the request names, which can belong to another project."),
    "instances.failover": ("write", None),
    "instances.import": ("irreversible", "Runs a SQL dump or loads a CSV file, which can drop and overwrite tables."),
    "instances.insert": ("money", "New instances are billed."),
    "instances.patch": ("write", None),
    "instances.update": ("write", None),
    "instances.pointInTimeRestore": ("irreversible", "Restores the database to an earlier time; what was written since is gone from it."),
    "instances.preCheckMajorVersionUpgrade": ("read", "Checks whether an upgrade would work; changes nothing."),
    "instances.promoteReplica": ("write", "Stops replication and makes the replica a standalone primary."),
    "instances.reencrypt": ("write", None),
    "instances.releaseSsrsLease": ("write", None),
    "instances.resetSslConfig": ("access", "Deletes every client certificate, so clients using them can no longer connect."),
    "instances.restart": ("write", None),
    "instances.restoreBackup": ("irreversible", "Replaces the target instance's data with the backup's."),
    "instances.rotateServerCa": ("access", "Changes the certificates clients trust when connecting."),
    "instances.startReplica": ("write", None),
    "instances.stopReplica": ("write", None),
    "instances.switchover": ("write", None),
    "instances.truncateLog": ("irreversible", "Empties the general and slow query log tables."),
    "operations.cancel": ("write", None),
    "projects.instances.performDiskShrink": ("write", None),
    "projects.instances.rescheduleMaintenance": ("write", None),
    "projects.instances.resetReplicaSize": ("write", None),
    "projects.instances.startExternalSync": ("irreversible", "Starts replicating an external database into the instance, replacing its data."),
    "projects.instances.verifyExternalSyncSettings": ("read", "Checks settings; changes nothing."),
    "sslCerts.createEphemeral": ("credential", "Returns a client certificate that lets its holder connect to the instance."),
    "sslCerts.delete": ("access", None),
    "sslCerts.insert": ("credential", "Returns the new client certificate with its private key."),
    "users.delete": ("access", None),
    "users.insert": ("credential", "Creates a database user and sets its password."),
    "users.update": ("credential", "Can set a database user's password."),
    "workloadCaptures.start": ("write", None),
    "workloadCaptures.startReplay": ("write", None),
    "workloadCaptures.stop": ("write", None),
    "workloadCaptures.stopReplay": ("write", None),
}
SQL_SETTINGS_WHEN = [
    ("access", "{ arg: body.settings.ipConfiguration.authorizedNetworks, present: true }"),
    ("access", '{ arg: body.settings.ipConfiguration.ipv4Enabled, equals: "true" }'),
    ("irreversible", '{ arg: body.settings.backupConfiguration.enabled, equals: "false" }'),
    ("irreversible", '{ arg: body.settings.backupConfiguration.pointInTimeRecoveryEnabled, equals: "false" }'),
    ("irreversible", '{ arg: body.settings.backupConfiguration.binaryLogEnabled, equals: "false" }'),
    ("irreversible", '{ arg: body.settings.deletionProtectionEnabled, equals: "false" }'),
    ("money", "{ arg: body.settings.tier, present: true }"),
]
SQL_SETTINGS_NOTE = (" Opening the instance to networks (authorizedNetworks, a public IP) is access; turning off backups,"
                     " point-in-time recovery, binary logging or deletion protection is irreversible, as dangerous as what"
                     " it protects; changing the machine tier is money.")

# ---------------------------------------------------------------- Storage
OBJ_NOTE = None
STORAGE = {
    "anywhereCaches.disable": ("write", None),
    "anywhereCaches.insert": ("money", "Anywhere Cache instances are billed."),
    "anywhereCaches.pause": ("write", None),
    "anywhereCaches.resume": ("write", None),
    "anywhereCaches.update": ("write", None),
    "buckets.delete": ("delete", "Only an empty bucket can be deleted, and soft delete keeps a deleted bucket restorable for a while."),
    "buckets.insert": ("write", None),
    "buckets.lockRetentionPolicy": ("irreversible", "Locking a retention policy is permanent: neither the policy nor the bucket can be removed until every object has met it."),
    "buckets.patch": ("write", None),
    "buckets.update": ("write", None),
    "buckets.relocate": ("write", None),
    "buckets.restore": ("write", None),
    "buckets.setIamPolicy": ("access", None),
    "buckets.operations.advanceRelocateBucket": ("write", None),
    "buckets.operations.cancel": ("write", None),
    "folders.delete": ("delete", "Only an empty folder can be deleted."),
    "folders.deleteRecursive": ("irreversible", "Deletes the folder with every object in it."),
    "folders.insert": ("write", None),
    "folders.rename": ("write", None),
    "managedFolders.delete": ("delete", "Without allowNonEmpty, only an empty managed folder can be deleted."),
    "managedFolders.insert": ("write", None),
    "managedFolders.setIamPolicy": ("access", None),
    "managedFolders.update": ("write", None),
    "notifications.delete": ("delete", None),
    "notifications.insert": ("write", None),
    "objects.bulkRestore": ("write", None),
    "objects.compose": ("write", None),
    "objects.copy": ("write", "Overwrites the destination object if there is one, as S3's CopyObject does."),
    "objects.delete": ("irreversible", "Opfence cannot see whether the bucket keeps soft-deleted or noncurrent versions, so a deleted object counts as gone, as for S3."),
    "objects.insert": ("write", "Overwrites the object if there is one, as S3's PutObject does."),
    "objects.move": ("write", None),
    "objects.patch": ("write", None),
    "objects.restore": ("write", None),
    "objects.rewrite": ("write", None),
    "objects.setIamPolicy": ("access", None),
    "objects.update": ("write", None),
    "projects.hmacKeys.create": ("credential", "Returns the new HMAC key's secret."),
    "projects.hmacKeys.delete": ("access", None),
    "projects.hmacKeys.update": ("access", "Activates or deactivates an HMAC key."),
    "rapidCaches.disable": ("write", None),
    "rapidCaches.insert": ("money", "Rapid Cache instances are billed."),
    "rapidCaches.update": ("write", None),
}
for res in ("bucketAccessControls", "defaultObjectAccessControls", "objectAccessControls"):
    for m in ("delete", "insert", "patch", "update"):
        STORAGE[f"{res}.{m}"] = ("access", "Access control lists decide who can read and write the bucket's objects.")
ACL_WHEN = lambda p: [("access", f"{{ arg: query.{p}, matches: {PUBLIC_ACL} }}")]
BUCKET_WHEN = (ACL_WHEN("predefinedAcl") + ACL_WHEN("predefinedDefaultObjectAcl") + [
    ("access", "{ arg: body.acl, present: true }"),
    ("access", "{ arg: body.defaultObjectAcl, present: true }"),
    ("access", "{ arg: body.iamConfiguration, present: true }"),
    ("access", "{ arg: body.ipFilter, present: true }"),
    ("access", "{ arg: body.cors, present: true }"),
    ("irreversible", "{ arg: body.lifecycle, present: true }"),
    ("irreversible", "{ arg: body.softDeletePolicy, present: true }"),
    ("irreversible", '{ arg: body.versioning.enabled, equals: "false" }'),
])
BUCKET_NOTE = (" Public ACLs and changes to access control, IAM configuration, IP filtering or CORS are access; lifecycle rules"
               " (which delete objects later), soft delete settings and turning versioning off are irreversible.")
OBJ_ACL_NOTE = " A public predefined ACL or an ACL in the body is access."

# ---------------------------------------------------------------- Secret Manager
SECRETS = {
    "secrets.addVersion": ("credential", "Stores a new secret value."),
    "secrets.create": ("write", "Creates the secret without a value."),
    "secrets.delete": ("irreversible", "Deletes the secret with every version; no API returns their values to put them back."),
    "secrets.enableManagedRotation": ("write", None),
    "secrets.patch": ("write", None),
    "secrets.rotateSecret": ("credential", "Starts a rotation that stores a new secret value."),
    "secrets.setIamPolicy": ("access", None),
    "secrets.testIamPermissions": ("read", "Reports the caller's permissions; changes nothing."),
    "secrets.versions.destroy": ("irreversible", "A destroyed version's value is gone."),
    "secrets.versions.disable": ("write", "Apps reading the version stop getting it until it is enabled again."),
    "secrets.versions.enable": ("write", None),
    "secrets.versions.access": ("credential", "Returns the secret value."),
}

# ---------------------------------------------------------------- Resource Manager
READ_POSTS = {"getIamPolicy", "testIamPermissions", "getOrgPolicy", "getEffectiveOrgPolicy", "listOrgPolicies",
              "listAvailableOrgPolicyConstraints", "search", "getAncestry", "lintPolicy", "queryAuditableServices",
              "queryTestablePermissions", "queryGrantableRoles"}
CRM = {
    "projects.create": ("write", None),
    "projects.delete": ("delete", "The project shuts down at once and is deleted with everything in it after 30 days; until then it can be undeleted."),
    "projects.undelete": ("write", None),
    "projects.update": ("write", None),
    "projects.patch": ("write", None),
    "projects.move": ("access", "Moves the project under another folder or organization, whose policies then apply to it."),
    "folders.create": ("write", None),
    "folders.delete": ("delete", "Only an empty folder can be deleted, and it can be undeleted for 30 days."),
    "folders.patch": ("write", None),
    "folders.undelete": ("write", None),
    "folders.move": ("access", "Moves the folder under another parent, whose policies then apply to it."),
    "liens.create": ("write", "A lien stops the project from being deleted."),
    "liens.delete": ("delete", "Removing a lien turns off the protection against deleting the project, which is as dangerous as deleting it."),
    "tagValues.tagHolds.create": ("write", None),
    "tagValues.tagHolds.delete": ("write", None),
}
CRM_ACCESS_NOTE = {"setOrgPolicy": "Organization policies are guardrails, such as forbidding public IPs.",
                   "clearOrgPolicy": "Organization policies are guardrails, such as forbidding public IPs.",
                   "tag": "Tags can be conditions of IAM and organization policies."}

# ---------------------------------------------------------------- IAM
IAM_CRED = {
    "projects.serviceAccounts.keys.create": "Returns the new service account key's private key.",
    "projects.serviceAccounts.keys.upload": "Adds a key the caller holds, which can then sign in as the service account.",
    "projects.serviceAccounts.signBlob": "Signs as the service account.",
    "projects.serviceAccounts.signJwt": "Signs a JWT as the service account, which can be exchanged for its access token.",
    "projects.locations.oauthClients.credentials.create": "Returns the OAuth client's new secret.",
    "locations.workforcePools.providers.scimTenants.tokens.create": "Returns a SCIM token.",
}
IAMCRED_NOTES = {
    "projects.serviceAccounts.generateAccessToken": "Returns an access token that acts as the service account.",
    "projects.serviceAccounts.generateIdToken": "Returns an ID token that identifies as the service account.",
    "projects.serviceAccounts.signBlob": "Signs as the service account.",
    "projects.serviceAccounts.signJwt": "Signs a JWT as the service account, which can be exchanged for its access token.",
}

# ---------------------------------------------------------------- Compute Engine (27b)
FW = "Firewall rules decide what traffic reaches the network's VMs."
ARMOR = "Cloud Armor policies decide which requests reach the backends."
LB = "Load balancer settings decide what is served at a public address, and with which certificates, IAP and Cloud Armor settings."
META = ("Metadata holds startup scripts, which run as root when a VM boots, and SSH keys, which let their holders log in; "
        "running commands on a VM can do anything it can.")
PSC = "Private Service Connect connects networks and services across projects."
COMPUTE_METHOD = {  # by method name, for every resource
    "testIamPermissions": ("read", "Reports the caller's permissions; changes nothing."),
    "getHealth": ("read", "Reports health; changes nothing."),
    "getVersion": ("read", "Reports versions; changes nothing."),
    "validate": ("read", "Checks a configuration; changes nothing."),
    "preview": ("read", "Shows what a change would do; changes nothing."),
    "wait": ("read", "Waits for an operation; changes nothing."),
    "setIamPolicy": ("access", "Decides who can use the resource, and can share it with other projects or everyone."),
    "setLabels": ("write", None), "bulkSetLabels": ("write", None),
}
COMPUTE = {  # by resource (without its region, global or zone prefix) and method
    "addresses": {"delete": ("irreversible", "A released address goes back to Google's pool; the same IP address cannot be reserved again."),
                  "insert": ("money", "Static external addresses are billed."), "move": ("write", None)},
    "advice": {"calendarMode": ("read", "Recommends capacity; changes nothing."), "capacity": ("read", "Recommends capacity; changes nothing."),
               "capacityHistory": ("read", "Reports capacity; changes nothing.")},
    "autoscalers": {"delete": ("delete", "The group keeps its current size."),
                    "*": ("money", "An autoscaler decides how many VMs run, and VMs are billed.")},
    "backendBuckets": {"addSignedUrlKey": ("credential", "Adds a signing key; whoever holds it can sign URLs to the bucket's content."),
                       "deleteSignedUrlKey": ("access", None), "delete": ("delete", None), "*": ("access", LB)},
    "backendServices": {"addSignedUrlKey": ("credential", "Adds a signing key; whoever holds it can sign URLs to the service's content."),
                        "deleteSignedUrlKey": ("access", None), "delete": ("delete", None), "*": ("access", LB)},
    "commitments": {"*": ("money", "A commitment is a one- or three-year purchase that cannot be cancelled.")},
    "crossSiteNetworks": {"insert": ("money", "Cross-Site Interconnect is billed."), "delete": ("delete", None), "*": ("write", None)},
    "wireGroups": {"insert": ("money", "Cross-Site Interconnect wires are billed."), "delete": ("delete", None), "*": ("write", None)},
    "disks": {"addResourcePolicies": ("write", None), "bulkInsert": ("money", "New disks are billed."), "createSnapshot": ("write", None),
              "delete": ("irreversible", "The disk's data is gone, unless a snapshot of it was taken."), "insert": ("money", "New disks are billed."),
              "removeResourcePolicies": ("irreversible", "Removing a snapshot schedule turns off the disk's backups, which is as dangerous as losing what they protect."),
              "resize": ("money", "A disk can only grow, and its size is billed."), "*": ("write", None)},
    "externalVpnGateways": {"delete": ("delete", None), "*": ("write", None)},
    "firewallPolicies": {"*": ("access", FW)}, "networkFirewallPolicies": {"*": ("access", FW)},
    "organizationSecurityPolicies": {"*": ("access", ARMOR)}, "securityPolicies": {"*": ("access", ARMOR)},
    "networkEdgeSecurityServices": {"*": ("access", ARMOR)},
    "firewalls": {"*": ("access", FW)},
    "forwardingRules": {"delete": ("delete", None), "*": ("access", "Forwarding rules serve a backend at an IP address, often a public one.")},
    "futureReservations": {"insert": ("money", "Reserved capacity is billed."), "update": ("money", "Reserved capacity is billed."),
                           "delete": ("delete", None), "*": ("write", None)},
    "images": {"delete": ("irreversible", "A deleted image cannot be restored."), "*": ("write", None)},
    "instanceGroupManagerResizeRequests": {"insert": ("money", "Adds VMs, which are billed."), "*": ("write", None)},
    "instanceGroupManagers": {
        "abandonInstances": ("write", "The VMs keep running outside the group."),
        "applyUpdatesToInstances": ("irreversible", "Can replace the group's VMs, recreating their disks."),
        "createInstances": ("money", "New VMs are billed."),
        "delete": ("irreversible", "Deletes the group with its VMs and their disks."),
        "deleteInstances": ("irreversible", "Deletes VMs with their disks."),
        "deletePerInstanceConfigs": ("irreversible", "Per-instance configs keep stateful disks; without them a recreated VM loses its disk."),
        "patchPerInstanceConfigs": ("irreversible", "Per-instance configs keep stateful disks; without them a recreated VM loses its disk."),
        "updatePerInstanceConfigs": ("irreversible", "Per-instance configs keep stateful disks; without them a recreated VM loses its disk."),
        "insert": ("money", "The group starts VMs, which are billed."),
        "listManagedInstances": ("read", "Lists; changes nothing."), "listPerInstanceConfigs": ("read", "Lists; changes nothing."),
        "listErrors": ("read", "Lists; changes nothing."),
        "patch": ("irreversible", "A patch can change the template or the update policy and start replacing the group's VMs, recreating their disks."),
        "recreateInstances": ("irreversible", "Recreates VMs, which recreates their disks."),
        "resize": ("irreversible", "Shrinking the group deletes VMs with their disks; growing it is billed."),
        "resumeInstances": ("money", "Resumed VMs are billed."), "startInstances": ("money", "Started VMs are billed."),
        "setTargetPools": ("access", "Target pools serve the group's VMs at a load balancer's address."),
        "*": ("write", None)},
    "instanceGroups": {"listInstances": ("read", "Lists; changes nothing."), "delete": ("delete", None), "*": ("write", None)},
    "instanceSettings": {"patch": ("irreversible", "Instance settings hold metadata for every VM in the zone. " + META)},
    "instanceTemplates": {"delete": ("delete", None), "*": ("write", None)},
    "instances": {
        "addAccessConfig": ("access", "Gives the VM an external IP address."), "addNetworkInterface": ("access", "Connects the VM to another network."),
        "bulkInsert": ("money", "New VMs are billed."), "insert": ("money", "New VMs are billed."),
        "delete": ("irreversible", "The boot disk, and other disks set to auto-delete, are deleted with the VM."),
        "reset": ("write", "A hard reset: what was in memory is lost."),
        "resume": ("money", "A resumed VM is billed."), "start": ("money", "A started VM is billed."),
        "startWithEncryptionKey": ("money", "A started VM is billed."),
        "setMachineResources": ("money", "Machine resources are billed."), "setMachineType": ("money", "The machine type decides the price."),
        "setMetadata": ("irreversible", META),
        "setSecurityPolicy": ("access", ARMOR),
        "setServiceAccount": ("access", "Changes the identity, and so the permissions, of the code running on the VM."),
        "setShieldedInstanceIntegrityPolicy": ("access", "Shielded VM settings check that the VM boots what it should."),
        "updateShieldedInstanceConfig": ("access", "Shielded VM settings check that the VM boots what it should."),
        "setTags": ("access", "Network tags decide which firewall rules apply to the VM."),
        "update": ("irreversible", "Replaces the VM's properties, its metadata among them. " + META),
        "updateAccessConfig": ("access", "Changes the VM's external IP address."),
        "updateNetworkInterface": ("access", "Changes the networks the VM is connected to and its external address."),
        "*": ("write", None)},
    "instantSnapshotGroups": {"delete": ("irreversible", "A deleted snapshot cannot be restored from."), "*": ("write", None)},
    "instantSnapshots": {"delete": ("irreversible", "A deleted snapshot cannot be restored from."), "*": ("write", None)},
    "interconnectAttachmentGroups": {"delete": ("delete", None), "*": ("write", None)},
    "interconnectGroups": {"createMembers": ("money", "Interconnects are billed."), "delete": ("delete", None), "*": ("write", None)},
    "interconnectAttachments": {"insert": ("money", "VLAN attachments are billed."), "delete": ("delete", None), "*": ("write", None)},
    "interconnects": {"insert": ("money", "Interconnects are billed."), "delete": ("delete", None), "*": ("write", None)},
    "licenseCodes": {}, "licenses": {"delete": ("delete", None), "*": ("write", None)},
    "machineImages": {"delete": ("irreversible", "A machine image is a VM's backup; a deleted one cannot be restored from."), "*": ("write", None)},
    "networkAttachments": {"delete": ("delete", None), "*": ("access", PSC)},
    "serviceAttachments": {"delete": ("delete", None), "*": ("access", PSC)},
    "networkEndpointGroups": {"listNetworkEndpoints": ("read", "Lists; changes nothing."), "delete": ("delete", None), "*": ("write", None)},
    "networks": {"addPeering": ("access", "Peering connects the network's VMs with another network, which can belong to another project."),
                 "updatePeering": ("access", "Peering connects the network's VMs with another network, which can belong to another project."),
                 "delete": ("delete", None), "*": ("write", None)},
    "nodeGroups": {"addNodes": ("money", "Sole-tenant nodes are billed."), "insert": ("money", "Sole-tenant nodes are billed."),
                   "patch": ("money", "Changes the group's size or autoscaling, and nodes are billed."),
                   "delete": ("irreversible", "Counted as irreversible in case VMs still run on the nodes."),
                   "deleteNodes": ("irreversible", "Counted as irreversible in case VMs still run on the nodes."),
                   "listNodes": ("read", "Lists; changes nothing."), "*": ("write", None)},
    "nodeTemplates": {"delete": ("delete", None), "*": ("write", None)},
    "notificationEndpoints": {"delete": ("delete", None), "*": ("write", None)},
    "operations": {"delete": ("write", "Deletes the record of an operation, not what it did.")},
    "organizationOperations": {"delete": ("write", "Deletes the record of an operation, not what it did.")},
    "packetMirrorings": {"delete": ("delete", None), "*": ("access", "Packet mirroring copies the network's traffic to a collector.")},
    "previewFeatures": {"*": ("write", None)},
    "projects": {"disableXpnHost": ("access", "Shared VPC lets other projects use this project's networks."),
                 "disableXpnResource": ("access", "Shared VPC lets other projects use this project's networks."),
                 "enableXpnHost": ("access", "Shared VPC lets other projects use this project's networks."),
                 "enableXpnResource": ("access", "Shared VPC lets other projects use this project's networks."),
                 "listXpnHosts": ("read", "Lists; changes nothing."),
                 "setCloudArmorTier": ("money", "The Cloud Armor tier is billed."),
                 "setCommonInstanceMetadata": ("irreversible", "Project metadata applies to every VM in the project. " + META),
                 "*": ("write", None)},
    "publicAdvertisedPrefixes": {"announce": ("access", "Announces the addresses to the internet."), "delete": ("delete", None), "*": ("write", None)},
    "publicDelegatedPrefixes": {"announce": ("access", "Announces the addresses to the internet."), "delete": ("delete", None), "*": ("write", None)},
    "reservationBlocks": {"*": ("write", None)}, "reservationSubBlocks": {"*": ("write", None)}, "reservationSlots": {"*": ("write", None)},
    "reservations": {"insert": ("money", "Reserved capacity is billed."), "resize": ("money", "Reserved capacity is billed."),
                     "update": ("money", "Reserved capacity is billed."),
                     "delete": ("delete", "Released capacity may not be available again."), "*": ("write", None)},
    "resourcePolicies": {"patch": ("irreversible", "Can shorten how long scheduled snapshots are kept."), "delete": ("delete", None), "*": ("write", None)},
    "rolloutPlans": {"delete": ("delete", None), "*": ("write", None)},
    "rollouts": {"delete": ("delete", None), "*": ("write", None)},
    "routers": {"delete": ("delete", None), "*": ("write", None)},
    "routes": {"delete": ("delete", None), "*": ("access", "Routes decide where the network's traffic goes, and can send it through a VM.")},
    "snapshotSettings": {"*": ("write", None)},
    "snapshots": {"delete": ("irreversible", "A deleted snapshot cannot be restored from."), "*": ("write", None)},
    "sslCertificates": {"delete": ("delete", None), "*": ("write", None)},
    "sslPolicies": {"patch": ("access", "Can allow older TLS versions and weaker ciphers."), "delete": ("delete", None), "*": ("write", None)},
    "storagePools": {"insert": ("money", "Provisioned capacity is billed."), "update": ("money", "Provisioned capacity is billed."),
                     "delete": ("irreversible", "Counted as irreversible in case disks remain in the pool.")},
    "subnetworks": {"delete": ("delete", None), "*": ("write", None)},
    "targetGrpcProxies": {"delete": ("delete", None), "*": ("access", LB)},
    "targetHttpProxies": {"delete": ("delete", None), "*": ("access", LB)},
    "targetHttpsProxies": {"delete": ("delete", None), "setQuicOverride": ("write", None), "*": ("access", LB)},
    "targetSslProxies": {"delete": ("delete", None), "setProxyHeader": ("write", None), "*": ("access", LB)},
    "targetTcpProxies": {"delete": ("delete", None), "setProxyHeader": ("write", None), "*": ("access", LB)},
    "targetInstances": {"delete": ("delete", None), "*": ("access", LB)},
    "targetPools": {"delete": ("delete", None), "addInstance": ("access", "Serves the VM at the load balancer's address."),
                    "removeInstance": ("write", None), "addHealthCheck": ("write", None), "removeHealthCheck": ("write", None), "*": ("access", LB)},
    "targetVpnGateways": {"delete": ("delete", None), "*": ("write", None)},
    "vpnGateways": {"delete": ("delete", None), "*": ("write", None)},
    "vpnTunnels": {"insert": ("access", "Connects the network to another network over the internet."), "delete": ("delete", None), "*": ("write", None)},
    "urlMaps": {"invalidateCache": ("write", None), "delete": ("delete", None), "*": ("access", "URL maps decide which backend serves each path.")},
    "vmExtensionPolicies": {"delete": ("write", None),
                            "*": ("irreversible", "Installs extensions, programs that run on matching VMs; running code on a VM can do anything it can.")},
    "hosts": {},
    "frontendSettings": {"*": ("money", "Billing bundle settings decide how load balancing is billed.")},
}
for _r in ("compositeHealthChecks", "healthAggregationPolicies", "healthCheckServices", "healthChecks", "httpHealthChecks",
           "httpsHealthChecks", "healthSources"):
    COMPUTE[_r] = {"delete": ("delete", None), "*": ("write", None)}
COMPUTE_WHEN = {
    "instances.setDeletionProtection": ([("irreversible", '{ arg: query.deletionProtection, equals: "false" }')],
                                        "Turning deletion protection off is as dangerous as deleting the VM."),
    "instances.setDiskAutoDelete": ([("irreversible", '{ arg: query.autoDelete, equals: "true" }')],
                                    "Setting a disk to auto-delete means deleting the VM deletes the disk too."),
}

def compute_base(res_name):
    import re as _re
    b = _re.sub(r"^(region|global|zone)(?=[A-Z])", "", res_name)
    return b[0].lower() + b[1:]

# ---------------------------------------------------------------- GKE (27b)
GKE_ACCESS_FIELDS = ["desiredMasterAuthorizedNetworksConfig", "desiredControlPlaneEndpointsConfig", "desiredPrivateClusterConfig",
                     "desiredEnablePrivateEndpoint", "desiredDefaultEnablePrivateNodes", "desiredAuthenticatorGroupsConfig",
                     "desiredAnonymousAuthenticationConfig", "desiredRbacBindingConfig", "desiredIdentityServiceConfig",
                     "desiredWorkloadIdentityConfig", "desiredBinaryAuthorization", "desiredShieldedNodes",
                     "desiredNodePoolAutoConfigNetworkTags"]
GKE = {
    "clusters.create": ("money", "A cluster's nodes and control plane are billed."),
    "clusters.delete": ("irreversible", "Deletes the cluster with its nodes; its Kubernetes objects, Secrets among them, are gone unless Backup for GKE kept them."),
    "clusters.update": ("write", None),
    "clusters.updateMaster": ("write", None), "clusters.master": ("write", None),
    "clusters.setAddons": ("write", None), "clusters.addons": ("write", None),
    "clusters.setLegacyAbac": ("access", "Legacy ABAC gives every service account in the cluster broad permissions."),
    "clusters.legacyAbac": ("access", "Legacy ABAC gives every service account in the cluster broad permissions."),
    "clusters.setLocations": ("money", "Nodes in more zones are billed."), "clusters.locations": ("money", "Nodes in more zones are billed."),
    "clusters.setLogging": ("write", None), "clusters.logging": ("write", None),
    "clusters.setMonitoring": ("write", None), "clusters.monitoring": ("write", None),
    "clusters.setMaintenancePolicy": ("write", None),
    "clusters.setMasterAuth": ("credential", "Sets the cluster's basic-auth password or client certificate."),
    "clusters.setNetworkPolicy": ("access", "Network policy decides which pods can reach each other."),
    "clusters.setResourceLabels": ("write", None), "clusters.resourceLabels": ("write", None),
    "clusters.startIpRotation": ("write", "Clients need the cluster's new address and certificate once it completes."),
    "clusters.completeIpRotation": ("write", None), "clusters.completeControlPlaneUpgrade": ("write", None),
    "clusters.nodePools.create": ("money", "Nodes are billed."),
    "clusters.nodePools.delete": ("delete", "Deletes the pool's nodes; their pods are rescheduled where they fit, and the pool can be created again."),
    "clusters.nodePools.rollback": ("write", None), "clusters.nodePools.update": ("write", None), "clusters.nodePools.completeUpgrade": ("write", None),
    "clusters.nodePools.setAutoscaling": ("money", "Autoscaling decides how many nodes run, and nodes are billed."),
    "clusters.nodePools.autoscaling": ("money", "Autoscaling decides how many nodes run, and nodes are billed."),
    "clusters.nodePools.setSize": ("money", "Nodes are billed."),
    "clusters.nodePools.setManagement": ("write", None),
    "operations.cancel": ("write", None),
}
GKE_SECRET_PATHS = ["**.masterAuth.password", "**.masterAuth.clientKey"]

# ---------------------------------------------------------------- Cloud Run (27b)
RUN_REGIONS = ["africa-south1", "asia-east1", "asia-east2", "asia-northeast1", "asia-northeast2", "asia-northeast3", "asia-south1", "asia-south2",
               "asia-southeast1", "asia-southeast2", "asia-southeast3", "australia-southeast1", "australia-southeast2", "europe-central2",
               "europe-north1", "europe-north2", "europe-southwest1", "europe-west1", "europe-west10", "europe-west12", "europe-west2",
               "europe-west3", "europe-west4", "europe-west6", "europe-west8", "europe-west9", "me-central1", "me-central2", "me-west1",
               "northamerica-northeast1", "northamerica-northeast2", "northamerica-south1", "southamerica-east1", "southamerica-west1",
               "us-central1", "us-east1", "us-east4", "us-east5", "us-south1", "us-west1", "us-west2", "us-west3", "us-west4"]
RUN_ENV = "**.env.value"
RUN_ENV_NOTE = ("Returns the containers' environment variables. The proxy holds their values: the agent sees tokens, which a "
                "write of the same object may carry back.")
RUN_OVERRIDES = "Overrides change the containers' command, arguments and environment, which can run anything the job's identity can."

def run_classify(key, trail, http):
    method, res = trail[-1], (trail[-2] if len(trail) > 1 else "")
    if method == "setIamPolicy":
        return "access", "Decides who can call or change it; allUsers makes a service public.", []
    if method == "testIamPermissions":
        return "read", "Reports the caller's permissions; changes nothing.", []
    if res == "operations":
        return {"delete": ("write", "Deletes the record of an operation, not what it did."),
                "wait": ("credential", "Returns the operation, which carries the resource it acts on with its environment variables. " +
                         RUN_ENV_NOTE.split(". ", 1)[1])}[method] + ([],)
    if res == "domainmappings":
        return ("access", "Serves the service at a public domain.", []) if method == "create" else ("delete", None, [])
    if method == "delete":
        return "delete", "Can be deployed again from its image and settings.", []
    if method == "run":
        return "write", "Runs the job's containers, which do whatever the job does.", [("irreversible", "{ arg: body.overrides, present: true }")]
    if method in ("cancel", "start", "stop"):
        return "write", None, []
    if method in ("create", "patch") or method.startswith("replace"):
        return "write", None, []
    if method in ("exportImage", "submit", "upload"):
        return "write", None, []
    return None

# ---------------------------------------------------------------- Cloud Functions (27b)
FN_ENV = ["**.environmentVariables", "**.buildEnvironmentVariables"]
FN = {
    "call": ("write", "Runs the function with the data given; it does whatever the function does."),
    "create": ("write", None), "patch": ("write", None), "delete": ("delete", "Can be deployed again from its source."),
    "generateDownloadUrl": ("read", "Returns a signed URL to the function's source, which the caller may already read."),
    "generateUploadUrl": ("write", "Returns a signed URL to upload new source to."),
    "setIamPolicy": ("access", "Decides who can call or change the function; allUsers makes it public."),
    "testIamPermissions": ("read", "Reports the caller's permissions; changes nothing."),
}

# ---------------------------------------------------------------- App Engine (27b)
GAE_ENV = ["**.envVariables", "**.buildEnvVariables"]
GAE = {
    "create": ("write", "An App Engine application cannot be deleted, and its region cannot be changed."),
    "patch": ("write", None), "repair": ("write", None),
    "authorizedCertificates": ("access", "Certificates decide what clients trust."),
    "domainMappings.create": ("access", "Serves the app at a public domain."), "domainMappings.patch": ("access", "Serves the app at a public domain."),
    "domainMappings.delete": ("delete", None),
    "ingressRules": ("access", "Firewall rules decide which addresses reach the app."),
    "services.delete": ("delete", "Deletes the service with its versions, which can be deployed again from their source."),
    "services.patch": ("write", None),
    "versions.create": ("write", None), "versions.patch": ("write", None), "versions.exportAppImage": ("write", None),
    "versions.delete": ("delete", "Can be deployed again from its source."),
    "instances.debug": ("irreversible", "Lets the holder of the SSH key in the request log in to the instance; running commands on it can do anything it can."),
    "instances.delete": ("write", "App Engine starts another instance as needed."),
}

# ---------------------------------------------------------------- BigQuery (27c)
BQ_TRUNCATE = [("irreversible", '{ arg: body.configuration.%s.writeDisposition, equals: "WRITE_TRUNCATE" }'),
               ("irreversible", '{ arg: body.configuration.%s.writeDisposition, equals: "WRITE_TRUNCATE_DATA" }')]
BQ_JOB_WHEN = ([("write", "{ arg: body.configuration.query.destinationTable, present: true }")] +
               [(c, w % "query") for c, w in BQ_TRUNCATE] +
               [("money", '{ arg: body.configuration.query.continuous, equals: "true" }'),
                ("write", "{ arg: body.configuration.load, present: true }")] +
               [(c, w % "load") for c, w in BQ_TRUNCATE] +
               [("write", "{ arg: body.configuration.copy, present: true }")] +
               [(c, w % "copy") for c, w in BQ_TRUNCATE] +
               [("access", "{ arg: body.configuration.extract, present: true }")])
BQ_JOB_NOTE = ("A query job's class comes from its SQL, read as GoogleSQL (legacy SQL cannot change data). Writing the results "
               "to a table is a write, and overwriting one (WRITE_TRUNCATE) irreversible, as is a load or copy job that "
               "overwrites; an extract writes the table to the Cloud Storage location the job names, which can belong to "
               "another project, so it is access; a continuous query runs, and is billed, until it is stopped.")
BQ = {
    "datasets.delete": ("delete", "Only an empty dataset, unless deleteContents is set.",
                        [("irreversible", '{ arg: query.deleteContents, equals: "true" }')]),
    "datasets.insert": ("write", None, [("access", "{ arg: body.access, present: true }")]),
    "datasets.undelete": ("write", None, []),
    "jobs.cancel": ("write", None, []),
    "jobs.delete": ("write", "Deletes the record of a job, not what it did.", []),
    "models.delete": ("delete", "A model can be trained again from its data.", []),
    "models.patch": ("write", None, [("irreversible", "{ arg: body.expirationTime, present: true }")]),
    "routines.delete": ("delete", "A routine can be created again from its definition.", []),
    "routines.insert": ("write", None, []), "routines.update": ("write", None, []),
    "tabledata.insertAll": ("write", None, []),
    "tables.delete": ("irreversible", "A deleted table can be recovered only within the dataset's time travel window, which "
                      "can be as short as two days; counted as gone, as SQL's DROP TABLE is.", []),
    "tables.insert": ("write", None, []),
}
BQ_EXPIRY = [("irreversible", "{ arg: body.%s, present: true }")]
for _k in ("datasets.patch", "datasets.update"):
    BQ[_k] = ("write", "Access lists are access; table expiry, partition expiry and a shorter time travel window delete data "
              "later, so they are irreversible.",
              [("access", "{ arg: body.access, present: true }")] +
              [("irreversible", f"{{ arg: body.{f}, present: true }}") for f in
               ("defaultTableExpirationMs", "defaultPartitionExpirationMs", "maxTimeTravelHours")])
for _k in ("tables.patch", "tables.update"):
    BQ[_k] = ("write", "An expiration time, or partitions that expire, delete data later, so they are irreversible.",
              [("irreversible", "{ arg: body.expirationTime, present: true }"),
               ("irreversible", "{ arg: body.timePartitioning.expirationMs, present: true }")])

# ---------------------------------------------------------------- Spanner (27c)
SPANNER_SQL = ("The class comes from the SQL, read as both GoogleSQL and PostgreSQL, since a database speaks either and "
               "Opfence cannot tell which; SQL one of them cannot read keeps the rule's class.")
SPANNER_MUTATIONS = lambda base: [("delete", f"{{ arg: {base}.delete, present: true }}"),
                                  ("irreversible", f'{{ arg: {base}.delete.keySet.all, equals: "true" }}'),
                                  ("irreversible", f"{{ arg: {base}.delete.keySet.ranges, present: true }}")]
SPANNER = {
    "instanceConfigs.create": ("write", None, []), "instanceConfigs.delete": ("delete", None, []), "instanceConfigs.patch": ("write", None, []),
    "instances.create": ("money", "Instances are billed by their compute capacity.", []),
    "instances.delete": ("irreversible", "Deletes the instance with every database and backup in it.", []),
    "instances.move": ("write", None, []),
    "instances.patch": ("write", "Compute capacity is billed.", [("money", "{ arg: body.instance.nodeCount, present: true }"),
                                                                ("money", "{ arg: body.instance.processingUnits, present: true }"),
                                                                ("money", "{ arg: body.instance.autoscalingConfig, present: true }")]),
    "backups.copy": ("write", None, []), "backups.create": ("write", None, []),
    "backups.delete": ("irreversible", "A deleted backup cannot be restored from.", []),
    "backups.patch": ("write", "An earlier expire time deletes the backup sooner.", [("irreversible", "{ arg: body.expireTime, present: true }")]),
    "databases.addSplitPoints": ("write", None, []), "databases.changequorum": ("write", None, []),
    "databases.create": ("write", None, []),
    "databases.dropDatabase": ("irreversible", "Drops the database with its data.", []),
    "databases.patch": ("write", "Turning drop protection off is as dangerous as dropping the database.",
                        [("irreversible", '{ arg: body.enableDropProtection, equals: "false" }')]),
    "databases.restore": ("write", "Restores into a new database.", []),
    "databases.backupSchedules.create": ("write", None, []),
    "databases.backupSchedules.delete": ("irreversible", "Removing a backup schedule turns off the database's backups, as dangerous as losing what they protect.", []),
    "databases.backupSchedules.patch": ("write", "A shorter retention deletes backups sooner.",
                                        [("irreversible", "{ arg: body.retentionDuration, present: true }")]),
    "databases.sessions.adaptMessage": ("unknown", "Carries messages of another wire protocol, which Opfence does not read.", []),
    "databases.sessions.adapter": ("unknown", "Carries messages of another wire protocol, which Opfence does not read.", []),
    "databases.sessions.batchCreate": ("read", "Opens sessions; changes nothing.", []),
    "databases.sessions.create": ("read", "Opens a session; changes nothing.", []),
    "databases.sessions.delete": ("read", "Closes a session; changes nothing.", []),
    "databases.sessions.beginTransaction": ("read", "Starts a transaction; changes nothing until a commit.", []),
    "databases.sessions.rollback": ("read", "Rolls a transaction back; changes nothing.", []),
    "databases.sessions.read": ("read", "Reads rows.", []), "databases.sessions.streamingRead": ("read", "Reads rows.", []),
    "databases.sessions.partitionRead": ("read", "Plans a read; changes nothing.", []),
    "databases.sessions.partitionQuery": ("read", "Plans a query, which may only read; changes nothing.", []),
    "databases.sessions.commit": ("write", "A delete mutation deletes the rows its keys name; one for every key (keySet.all) "
                                  "or for key ranges can reach every row, so it is irreversible.", SPANNER_MUTATIONS("body.mutations")),
    "databases.sessions.batchWrite": ("write", "A delete mutation deletes the rows its keys name; one for every key (keySet.all) "
                                      "or for key ranges can reach every row, so it is irreversible.", SPANNER_MUTATIONS("body.mutationGroups.mutations")),
    "instancePartitions.create": ("money", "Instance partitions are billed by their compute capacity.", []),
    "instancePartitions.delete": ("irreversible", "Counted as irreversible in case databases remain in the partition.", []),
    "instancePartitions.patch": ("money", "Compute capacity is billed.", []),
}
SPANNER_SQL_RULES = {
    "databases.updateDdl": ("body.statements", "irreversible"),
    "databases.sessions.executeSql": ("body.sql", "irreversible"),
    "databases.sessions.executeStreamingSql": ("body.sql", "irreversible"),
    "databases.sessions.executeBatchDml": ("body.statements.sql", "irreversible"),
}
# Fixture bodies for rules that read SQL: (a read, the expected class), (a destructive one, its class).
SQL_SAMPLES = {
    ("google-cloud-sql", "*"): (({"database": "orders", "sqlStatement": "select id from orders limit 10"}, "read"),
                                ({"database": "orders", "sqlStatement": "drop table orders"}, "irreversible")),
    ("google-cloud-bigquery", "jobs.insert"): (({"configuration": {"query": {"query": "SELECT id FROM `acme-prod.sales.orders` LIMIT 10", "useLegacySql": False}}}, "read"),
                                               ({"configuration": {"query": {"query": "DELETE FROM sales.orders WHERE true", "useLegacySql": False}}}, "irreversible")),
    ("google-cloud-bigquery", "jobs.query"): (({"query": "SELECT id FROM `acme-prod.sales.orders` LIMIT 10", "useLegacySql": False}, "read"),
                                              ({"query": "DROP TABLE sales.orders", "useLegacySql": False}, "irreversible")),
    ("google-cloud-spanner", "databases.updateDdl"): (({"statements": ["CREATE INDEX SingersByName ON Singers(Name)"]}, "write"),
                                                      ({"statements": ["DROP TABLE Singers"]}, "irreversible")),
    ("google-cloud-spanner", "databases.sessions.executeSql"): (({"sql": "SELECT SingerId FROM Singers WHERE SingerId = @id"}, "read"),
                                                                ({"sql": "DELETE FROM Singers WHERE true"}, "irreversible")),
    ("google-cloud-spanner", "databases.sessions.executeStreamingSql"): (({"sql": "SELECT SingerId FROM Singers LIMIT 10"}, "read"),
                                                                         ({"sql": "UPDATE Singers SET Name = 'x' WHERE 1 = 1"}, "irreversible")),
    ("google-cloud-spanner", "databases.sessions.executeBatchDml"): (({"statements": [{"sql": "UPDATE Singers SET Name = 'x' WHERE SingerId = 1"}], "seqno": "1"}, "write"),
                                                                     ({"statements": [{"sql": "DELETE FROM Singers WHERE SingerId IS NOT NULL"}], "seqno": "1"}, "irreversible")),
}

# ---------------------------------------------------------------- Firestore, Datastore, Pub/Sub, Memorystore, Bigtable, DNS, KMS (27c)
OVERWRITE_IMPORT = "Imports overwrite entities and documents with the same keys."
EXPORT_GCS = "Writes the data to the Cloud Storage location the request names, which can belong to another project."
DOC_DELETES = "A write that deletes documents is irreversible, unless point-in-time recovery is on, which Opfence cannot see."
T27C = {
    "google-cloud-firestore": {
        "databases.bulkDeleteDocuments": ("irreversible", "Deletes every document in the collection groups it names, or in the whole database when it names none.", []),
        "databases.clone": ("write", None, []), "databases.create": ("write", None, []),
        "databases.delete": ("irreversible", "Deletes the database with its documents; only a backup can bring them back.", []),
        "databases.exportDocuments": ("access", EXPORT_GCS, []),
        "databases.importDocuments": ("irreversible", OVERWRITE_IMPORT, []),
        "databases.patch": ("write", "Turning delete protection or point-in-time recovery off is as dangerous as what they protect.",
                            [("irreversible", '{ arg: body.deleteProtectionState, equals: "DELETE_PROTECTION_DISABLED" }'),
                             ("irreversible", '{ arg: body.pointInTimeRecoveryEnablement, equals: "POINT_IN_TIME_RECOVERY_DISABLED" }')]),
        "databases.restore": ("write", "Restores into a new database.", []),
        "databases.backupSchedules.create": ("write", None, []),
        "databases.backupSchedules.delete": ("irreversible", "Removing a backup schedule turns off the database's backups, as dangerous as losing what they protect.", []),
        "databases.backupSchedules.patch": ("write", "A shorter retention deletes backups sooner.", [("irreversible", "{ arg: body.retention, present: true }")]),
        "databases.changeStreams.create": ("write", None, []), "databases.changeStreams.delete": ("delete", None, []),
        "databases.collectionGroups.fields.patch": ("write", "A TTL policy deletes documents once their time passes.", [("irreversible", "{ arg: body.ttlConfig, present: true }")]),
        "databases.collectionGroups.indexes.create": ("write", None, []),
        "databases.collectionGroups.indexes.delete": ("delete", "An index can be built again.", []),
        "databases.documents.batchGet": ("read", "Reads documents.", []),
        "databases.documents.batchWrite": ("write", DOC_DELETES, [("irreversible", "{ arg: body.writes.delete, present: true }")]),
        "databases.documents.commit": ("write", DOC_DELETES, [("irreversible", "{ arg: body.writes.delete, present: true }")]),
        "databases.documents.write": ("write", DOC_DELETES, [("irreversible", "{ arg: body.writes.delete, present: true }")]),
        "databases.documents.beginTransaction": ("read", "Starts a transaction; changes nothing until a commit.", []),
        "databases.documents.rollback": ("read", "Rolls a transaction back; changes nothing.", []),
        "databases.documents.createDocument": ("write", None, []),
        "databases.documents.delete": ("irreversible", "A deleted document is gone, unless point-in-time recovery is on, which Opfence cannot see.", []),
        "databases.documents.patch": ("write", None, []),
        "databases.documents.executePipeline": ("read", "Runs a query pipeline, which reads.", []),
        "databases.documents.listCollectionIds": ("read", "Lists; changes nothing.", []),
        "databases.documents.listen": ("read", "Streams changes; changes nothing.", []),
        "databases.documents.partitionQuery": ("read", "Plans a query; changes nothing.", []),
        "databases.documents.runAggregationQuery": ("read", "Runs a query.", []),
        "databases.documents.runQuery": ("read", "Runs a query.", []),
        "databases.userCreds.create": ("credential", "Returns the new user's password.", []),
        "databases.userCreds.resetPassword": ("credential", "Returns a new password.", []),
        "databases.userCreds.delete": ("access", None, []), "databases.userCreds.disable": ("access", None, []),
        "databases.userCreds.enable": ("access", None, []),
        "backups.delete": ("irreversible", "A deleted backup cannot be restored from.", []),
    },
    "google-cloud-datastore": {
        "allocateIds": ("write", None, []), "reserveIds": ("write", None, []),
        "beginTransaction": ("read", "Starts a transaction; changes nothing until a commit.", []),
        "rollback": ("read", "Rolls a transaction back; changes nothing.", []),
        "lookup": ("read", "Reads entities.", []), "runQuery": ("read", "Runs a query.", []),
        "runAggregationQuery": ("read", "Runs a query.", []),
        "commit": ("write", "A delete mutation is irreversible, unless point-in-time recovery is on, which Opfence cannot see.",
                   [("irreversible", "{ arg: body.mutations.delete, present: true }")]),
        "export": ("access", EXPORT_GCS, []), "import": ("irreversible", OVERWRITE_IMPORT, []),
        "indexes.create": ("write", None, []), "indexes.delete": ("delete", "An index can be built again.", []),
    },
    "google-cloud-pubsub": {
        "schemas.commit": ("write", None, []), "schemas.create": ("write", None, []), "schemas.delete": ("delete", None, []),
        "schemas.deleteRevision": ("delete", None, []), "schemas.rollback": ("write", None, []),
        "schemas.validate": ("read", "Checks a schema; changes nothing.", []), "schemas.validateMessage": ("read", "Checks a message; changes nothing.", []),
        "snapshots.create": ("write", None, []), "snapshots.patch": ("write", None, []),
        "snapshots.delete": ("delete", "Subscriptions can no longer seek to it.", []),
        "subscriptions.acknowledge": ("delete", "Acknowledged messages leave the subscription; only one that retains them can seek back.", []),
        "subscriptions.create": ("write", "A push subscription sends every message to the endpoint it names, which can be anyone's.",
                                 [("access", "{ arg: body.pushConfig.pushEndpoint, present: true }")]),
        "subscriptions.delete": ("irreversible", "Drops the messages not yet delivered.", []),
        "subscriptions.detach": ("irreversible", "Drops the messages not yet delivered and stops delivery.", []),
        "subscriptions.modifyAckDeadline": ("write", None, []),
        "subscriptions.modifyPushConfig": ("access", "Sends every message to the endpoint it names, which can be anyone's.", []),
        "subscriptions.patch": ("write", "A push endpoint sends every message where it says; a shorter retention drops messages.",
                                [("access", "{ arg: body.subscription.pushConfig.pushEndpoint, present: true }"),
                                 ("irreversible", "{ arg: body.subscription.messageRetentionDuration, present: true }")]),
        "subscriptions.pull": ("read", "Receives messages; they stay until acknowledged.", []),
        "subscriptions.seek": ("irreversible", "Seeking to a later time or a snapshot acknowledges the messages before it.", []),
        "topics.create": ("write", None, []), "topics.delete": ("delete", "Subscriptions stay, detached from the topic.", []),
        "topics.patch": ("write", "A shorter retention drops messages.", [("irreversible", "{ arg: body.topic.messageRetentionDuration, present: true }")]),
        "topics.publish": ("write", None, []),
    },
    "google-cloud-memorystore": {
        "aclPolicies.create": ("access", None, []), "aclPolicies.delete": ("access", None, []), "aclPolicies.patch": ("access", None, []),
        "backupCollections.backups.delete": ("irreversible", "A deleted backup cannot be restored from.", []),
        "backupCollections.backups.export": ("access", EXPORT_GCS, []),
        "clusters.addTokenAuthUser": ("credential", "Creates a user that signs in with tokens.", []),
        "clusters.tokenAuthUsers.addAuthToken": ("credential", "Returns a new auth token.", []),
        "clusters.tokenAuthUsers.delete": ("access", None, []), "clusters.tokenAuthUsers.authTokens.delete": ("access", None, []),
        "clusters.backup": ("write", None, []), "clusters.create": ("money", "Clusters are billed by their size.", []),
        "clusters.delete": ("irreversible", "Deletes the cluster with its data.", []),
        "clusters.patch": ("money", "Changes the cluster's size or settings, and size is billed.", []),
        "clusters.rescheduleClusterMaintenance": ("write", None, []),
        "instances.create": ("money", "Instances are billed by their size.", []),
        "instances.delete": ("irreversible", "Deletes the instance with its data.", []),
        "instances.export": ("access", EXPORT_GCS, []),
        "instances.failover": ("write", "A failover with data protection off can lose recent writes.", []),
        "instances.import": ("irreversible", "Replaces the instance's data with the file's.", []),
        "instances.patch": ("money", "Changes the instance's size or settings, and size is billed; turning AUTH off is access.",
                            [("access", '{ arg: body.authEnabled, equals: "false" }')]),
        "instances.rescheduleMaintenance": ("write", None, []), "instances.upgrade": ("write", None, []),
    },
    "google-cloud-bigtable": {
        "create": ("money", "Instances are billed by their nodes.", []),
        "delete": ("irreversible", "Deletes the instance with every table and backup in it.", []),
        "partialUpdateInstance": ("write", None, []), "update": ("write", None, []),
        "appProfiles.create": ("write", None, []), "appProfiles.delete": ("delete", None, []), "appProfiles.patch": ("write", None, []),
        "clusters.create": ("money", "Nodes are billed.", []),
        "clusters.delete": ("delete", "The instance keeps its data in its other clusters; the last one cannot be deleted.", []),
        "clusters.partialUpdateCluster": ("money", "Nodes are billed.", []), "clusters.update": ("money", "Nodes are billed.", []),
        "clusters.updateMemoryLayer": ("money", None, []),
        "clusters.backups.copy": ("write", None, []), "clusters.backups.create": ("write", None, []),
        "clusters.backups.delete": ("irreversible", "A deleted backup cannot be restored from.", []),
        "clusters.backups.patch": ("write", "An earlier expire time deletes the backup sooner.", [("irreversible", "{ arg: body.expireTime, present: true }")]),
        "logicalViews.create": ("write", None, []), "logicalViews.delete": ("delete", None, []), "logicalViews.patch": ("write", None, []),
        "materializedViews.create": ("write", None, []), "materializedViews.delete": ("delete", None, []), "materializedViews.patch": ("write", None, []),
        "tables.checkConsistency": ("read", "Checks replication; changes nothing.", []),
        "tables.generateConsistencyToken": ("read", "Returns a token for checking replication; changes nothing.", []),
        "tables.create": ("write", None, []),
        "tables.delete": ("irreversible", "A deleted table can be undeleted for a few days, but counts as gone, as SQL's DROP TABLE does.", []),
        "tables.dropRowRange": ("irreversible", "Deletes every row with the prefix, or every row in the table.", []),
        "tables.modifyColumnFamilies": ("irreversible", "Can drop a column family with its data, or set a garbage collection rule that deletes cells.", []),
        "tables.patch": ("write", "Turning deletion protection off is as dangerous as deleting the table.",
                         [("irreversible", '{ arg: body.deletionProtection, equals: "false" }')]),
        "tables.restore": ("write", "Restores into a new table.", []), "tables.undelete": ("write", None, []),
        "tables.authorizedViews.create": ("access", "Authorized views decide who can read which rows.", []),
        "tables.authorizedViews.delete": ("access", "Authorized views decide who can read which rows.", []),
        "tables.authorizedViews.patch": ("access", "Authorized views decide who can read which rows.", []),
        "tables.schemaBundles.create": ("write", None, []), "tables.schemaBundles.delete": ("delete", None, []),
        "tables.schemaBundles.patch": ("write", None, []),
    },
    "google-cloud-dns": {
        "changes.create": ("access", "DNS records decide where a name's traffic goes: a changed record can send it anywhere.", []),
        "managedZones.create": ("write", None, []),
        "managedZones.delete": ("delete", "Only a zone without records of its own can be deleted.", []),
        "managedZones.patch": ("access", "Zone settings include DNSSEC and who can see private zones.", []),
        "managedZones.update": ("access", "Zone settings include DNSSEC and who can see private zones.", []),
        "outboundEndpoints.create": ("write", None, []), "outboundEndpoints.delete": ("delete", None, []), "outboundEndpoints.patch": ("write", None, []),
        "policies.create": ("access", "Server policies decide where networks send their queries.", []),
        "policies.delete": ("access", "Server policies decide where networks send their queries.", []),
        "policies.patch": ("access", "Server policies decide where networks send their queries.", []),
        "policies.update": ("access", "Server policies decide where networks send their queries.", []),
        "resourceRecordSets.create": ("access", "DNS records decide where a name's traffic goes.", []),
        "resourceRecordSets.delete": ("access", "DNS records decide where a name's traffic goes.", []),
        "resourceRecordSets.patch": ("access", "DNS records decide where a name's traffic goes.", []),
    },
    "google-cloud-kms": {
        "folders.updateAutokeyConfig": ("write", None, []), "folders.updateKajPolicyConfig": ("access", None, []),
        "organizations.updateKajPolicyConfig": ("access", None, []), "updateAutokeyConfig": ("write", None, []),
        "updateKajPolicyConfig": ("access", None, []),
        "generateRandomBytes": ("read", "Returns random bytes; changes nothing.", []),
        "updateEkmConfig": ("access", "External key managers hold the keys.", []),
        "ekmConnections.create": ("access", "External key managers hold the keys.", []),
        "ekmConnections.patch": ("access", "External key managers hold the keys.", []),
        "keyHandles.create": ("write", None, []), "keyRings.create": ("write", None, []),
        "keyRings.delete": ("delete", "Only an empty key ring can be deleted.", []),
        "keyRings.cryptoKeys.create": ("write", None, []),
        "keyRings.cryptoKeys.delete": ("irreversible", "Counted as irreversible in case versions remain: data encrypted with them could not be decrypted.", []),
        "keyRings.cryptoKeys.decrypt": ("credential", "Returns the plain text of data encrypted with the key.", []),
        "keyRings.cryptoKeys.encrypt": ("read", "Encrypts data the caller sends; changes nothing.", []),
        "keyRings.cryptoKeys.patch": ("write", None, []), "keyRings.cryptoKeys.updatePrimaryVersion": ("write", None, []),
        "keyRings.cryptoKeys.cryptoKeyVersions.asymmetricDecrypt": ("credential", "Returns the plain text of data encrypted with the key.", []),
        "keyRings.cryptoKeys.cryptoKeyVersions.rawDecrypt": ("credential", "Returns the plain text of data encrypted with the key.", []),
        "keyRings.cryptoKeys.cryptoKeyVersions.decapsulate": ("credential", "Returns the shared secret the ciphertext carries.", []),
        "keyRings.cryptoKeys.cryptoKeyVersions.asymmetricSign": ("credential", "Signs as the key; a signature can stand for its holder.", []),
        "keyRings.cryptoKeys.cryptoKeyVersions.macSign": ("credential", "Signs as the key; a MAC can stand for its holder.", []),
        "keyRings.cryptoKeys.cryptoKeyVersions.macVerify": ("read", "Checks a MAC; changes nothing.", []),
        "keyRings.cryptoKeys.cryptoKeyVersions.rawEncrypt": ("read", "Encrypts data the caller sends; changes nothing.", []),
        "keyRings.cryptoKeys.cryptoKeyVersions.create": ("write", None, []),
        "keyRings.cryptoKeys.cryptoKeyVersions.delete": ("irreversible", "Data encrypted with the version can no longer be decrypted.", []),
        "keyRings.cryptoKeys.cryptoKeyVersions.destroy": ("irreversible", "Once the scheduled time passes, which can be as soon as a day, data encrypted with the version can no longer be decrypted.", []),
        "keyRings.cryptoKeys.cryptoKeyVersions.restore": ("write", None, []),
        "keyRings.cryptoKeys.cryptoKeyVersions.import": ("write", None, []),
        "keyRings.cryptoKeys.cryptoKeyVersions.importTrustedKeyWrappedCryptoKeyVersion": ("write", None, []),
        "keyRings.cryptoKeys.cryptoKeyVersions.patch": ("write", "A disabled version cannot decrypt until it is enabled again.", []),
        "keyRings.importJobs.create": ("write", None, []),
        "singleTenantHsmInstances.create": ("money", "Single-tenant HSMs are billed.", []),
        "singleTenantHsmInstances.proposals.approve": ("access", None, []), "singleTenantHsmInstances.proposals.create": ("access", None, []),
        "singleTenantHsmInstances.proposals.delete": ("access", None, []), "singleTenantHsmInstances.proposals.execute": ("access", None, []),
    },
}
for _m in ("create", "delete", "patch", "update"):
    T27C["google-cloud-dns"][f"responsePolicies.{_m}"] = ("access", "Response policies rewrite the answers networks get to DNS queries.", [])
    T27C["google-cloud-dns"][f"responsePolicyRules.{_m}"] = ("access", "Response policies rewrite the answers networks get to DNS queries.", [])
T27C_GET = {  # GETs that return secrets
    ("google-cloud-memorystore", "instances.getAuthString"): ("credential", "Returns the instance's AUTH string, its password."),
}

# ---------------------------------------------------------------- providers
P = [
    dict(id="google-cloud-sql", verified="2026-10-23", title="Google Cloud SQL Admin API", docs="https://cloud.google.com/sql/docs/mysql/admin-api",
         hosts=["sqladmin.googleapis.com"], product="Cloud SQL", versions=[("sqladmin", "v1", ""), ("sqladmin", "v1beta4", "v1beta4")],
         about="Cloud SQL instances, databases, users, backups and SQL run through the API. gcloud sql calls v1beta4."),
    dict(id="google-cloud-storage", verified="2026-10-23", title="Google Cloud Storage JSON API", docs="https://cloud.google.com/storage/docs/json_api",
         hosts=["storage.googleapis.com"], product="Cloud Storage", versions=[("storage", "v1", "")],
         batch=["/batch/storage/v1"],
         about="Buckets, objects, access control and HMAC keys, through the JSON API that gcloud storage and the client libraries use. The XML API on the same host has no rules, so its writes are unknown. A batch (/batch/storage/v1) is decided request by request."),
    dict(id="google-cloud-secret-manager", verified="2026-10-23", title="Google Cloud Secret Manager", docs="https://cloud.google.com/secret-manager/docs/reference/rest",
         hosts=["secretmanager.googleapis.com", "secretmanager.*.rep.googleapis.com"], product="Secret Manager", versions=[("secretmanager", "v1", "")],
         about="Secrets and their versions, global and regional (secretmanager.<region>.rep.googleapis.com)."),
    dict(id="google-cloud-resource-manager", verified="2026-10-23", title="Google Cloud Resource Manager", docs="https://cloud.google.com/resource-manager/reference/rest",
         hosts=["cloudresourcemanager.googleapis.com"], product="", versions=[("cloudresourcemanager", "v3", ""), ("cloudresourcemanager", "v1", "v1"), ("cloudresourcemanager", "v2", "v2")],
         about="Projects, folders, organizations, IAM policies on them, organization policies, liens and tags. gcloud projects calls v1 and v3."),
    dict(id="google-cloud-iam", verified="2026-10-23", title="Google Cloud IAM", docs="https://cloud.google.com/iam/docs/reference/rest",
         hosts=["iam.googleapis.com"], product="", versions=[("iam", "v1", ""), ("iam", "v2", "v2")],
         about="Service accounts and their keys, custom roles, workload and workforce identity pools, OAuth clients and deny policies."),
    dict(id="google-cloud-iam-credentials", verified="2026-10-23", title="Google Cloud IAM Service Account Credentials", docs="https://cloud.google.com/iam/docs/reference/credentials/rest",
         hosts=["iamcredentials.googleapis.com"], product="", versions=[("iamcredentials", "v1", "")],
         about="Short-lived credentials for service accounts: access and ID tokens, and signatures."),
    dict(id="google-cloud-bigquery", title="Google BigQuery", docs="https://cloud.google.com/bigquery/docs/reference/rest",
         hosts=["bigquery.googleapis.com"], product="BigQuery", versions=[("bigquery", "v2", "")],
         about="Datasets, tables, jobs and the SQL they run, routines, models and row access policies. Query jobs are decided by their SQL, read as GoogleSQL, with the job's own settings (a destination table it overwrites, a load, copy or extract)."),
    dict(id="google-cloud-spanner", title="Google Cloud Spanner", docs="https://cloud.google.com/spanner/docs/reference/rest",
         hosts=["spanner.googleapis.com"], product="Spanner", versions=[("spanner", "v1", "")], id_skip=["instances"],
         about="Instances, databases, backups, schema changes and the SQL and mutations sent through sessions, through the REST API that gcloud uses. SQL is read as both GoogleSQL and PostgreSQL. The client libraries speak gRPC, which Opfence does not decode, so their requests are unknown."),
    dict(id="google-cloud-firestore", title="Google Cloud Firestore", docs="https://cloud.google.com/firestore/docs/reference/rest",
         hosts=["firestore.googleapis.com"], product="Firestore", versions=[("firestore", "v1", "")], id_skip=["databases"],
         about="Databases, documents, indexes, backups and imports and exports, through the REST API. Document paths of any depth are matched. The client libraries speak gRPC, which Opfence does not decode, so their requests are unknown."),
    dict(id="google-cloud-datastore", title="Google Cloud Datastore", docs="https://cloud.google.com/datastore/docs/reference/data/rest",
         hosts=["datastore.googleapis.com"], product="Datastore", versions=[("datastore", "v1", "")],
         about="Entities, by their commits and queries, indexes, imports and exports."),
    dict(id="google-cloud-pubsub", title="Google Cloud Pub/Sub", docs="https://cloud.google.com/pubsub/docs/reference/rest",
         hosts=["pubsub.googleapis.com"], product="Pub/Sub", versions=[("pubsub", "v1", "")],
         about="Topics, subscriptions, snapshots and schemas, and publishing and pulling messages through the REST API."),
    dict(id="google-cloud-memorystore", title="Google Cloud Memorystore for Redis", docs="https://cloud.google.com/memorystore/docs/redis/reference/rest",
         hosts=["redis.googleapis.com"], product="Memorystore", versions=[("redis", "v1", "")],
         about="Redis instances and clusters, their backups, AUTH strings and ACL policies. The data itself is Redis' own protocol, which does not pass through this API."),
    dict(id="google-cloud-bigtable", title="Google Cloud Bigtable Admin API", docs="https://cloud.google.com/bigtable/docs/reference/admin/rest",
         hosts=["bigtableadmin.googleapis.com"], product="Bigtable", versions=[("bigtableadmin", "v2", "")], id_skip=["instances"],
         about="Instances, clusters, tables, backups, app profiles and views. Reading and writing rows is the data API (bigtable.googleapis.com), which speaks gRPC and is not in the catalog."),
    dict(id="google-cloud-dns", title="Google Cloud DNS", docs="https://cloud.google.com/dns/docs/reference/rest/v1",
         hosts=["dns.googleapis.com"], product="Cloud DNS", versions=[("dns", "v1", "")],
         about="Managed zones, record sets and changes, policies and response policies. Changing where a name points is access."),
    dict(id="google-cloud-kms", title="Google Cloud Key Management Service", docs="https://cloud.google.com/kms/docs/reference/rest",
         hosts=["cloudkms.googleapis.com"], product="Cloud KMS", versions=[("cloudkms", "v1", "")],
         about="Key rings, keys and their versions, and the operations that use them: decrypting and signing are credential, destroying a version irreversible."),
    dict(id="google-cloud-compute", title="Google Compute Engine", docs="https://cloud.google.com/compute/docs/reference/rest/v1",
         hosts=["compute.googleapis.com"], product="Compute Engine", versions=[("compute", "v1", "")],
         batch=["/batch/compute/v1", "/batch/compute/beta", "/batch/compute/alpha"], version_param=("/compute/v1/", "/compute/{apiVersion}/"),
         about="VMs, disks, snapshots, images, networks, firewalls and load balancers. Rules match every API version (gcloud beta and alpha call beta and alpha), and gcloud's batch requests are decided request by request."),
    dict(id="google-cloud-gke", title="Google Kubernetes Engine", docs="https://cloud.google.com/kubernetes-engine/docs/reference/rest",
         hosts=["container.googleapis.com"], product="GKE", versions=[("container", "v1", "")], version_param=("/v1/", "/{apiVersion}/"),
         about="Clusters and node pools, by location and by the older zone paths. Rules match every API version (gcloud beta calls v1beta1). The workloads in a cluster are Kubernetes' own API, which this provider does not cover."),
    dict(id="google-cloud-run", title="Google Cloud Run", docs="https://cloud.google.com/run/docs/reference/rest",
         hosts=["run.googleapis.com"] + [f"{r}-run.googleapis.com" for r in RUN_REGIONS], product="Cloud Run",
         versions=[("run", "v2", ""), ("run", "v1", "v1")],
         about="Services, jobs, worker pools and their revisions and executions: v2, and v1's Knative-style API that gcloud run calls on each region's host (<region>-run.googleapis.com). Environment variables are held: the agent sees tokens that a write of the same object may carry back."),
    dict(id="google-cloud-functions", title="Google Cloud Functions", docs="https://cloud.google.com/functions/docs/reference/rest",
         hosts=["cloudfunctions.googleapis.com"], product="Cloud Functions", versions=[("cloudfunctions", "v2", ""), ("cloudfunctions", "v1", "v1")],
         about="Functions of both generations. Environment variables are held: the agent sees tokens that a write of the same function may carry back."),
    dict(id="google-cloud-app-engine", title="Google App Engine Admin API", docs="https://cloud.google.com/appengine/docs/admin-api/reference/rest",
         hosts=["appengine.googleapis.com"], product="App Engine", versions=[("appengine", "v1", "")],
         about="Applications, services, versions, instances, domain mappings, certificates and the firewall. Environment variables in a version (view=FULL) are held."),
]

def norm_param(n):
    special = {"projectsId": "project", "projectId": "project", "locationsId": "location", "organizationsId": "organization",
               "foldersId": "folder", "policiesId": "attachmentPoint", "policiesId1": "kind", "policiesId2": "policy",
               "accessId": "accessId"}
    # Knative's namespace and App Engine's app are the project.
    if (n, CURRENT.get("pid")) in {("namespacesId", "google-cloud-run"), ("appsId", "google-cloud-app-engine")}:
        return "project"
    if n in special:
        return special[n]
    if n.endswith("iesId"):
        return n[:-5] + "y"
    if n.endswith("sesId") and not n.endswith("asesId"):
        return n[:-4]
    if n.endswith("sId"):
        return n[:-3]
    if n.endswith("Id"):
        return n[:-2]
    return n

def template(path):
    names = re.findall(r"\{\+?([A-Za-z0-9_]+)\}", path)
    mapped = {n: norm_param(n) for n in names}
    if len(set(mapped.values())) != len(mapped):  # two would collide: keep the originals
        mapped = {n: n for n in names}
    out = re.sub(r"\{\+([A-Za-z0-9_]+)\}", lambda m: "{" + mapped[m.group(1)] + "*}", path)
    return re.sub(r"\{([A-Za-z0-9_]+)\}", lambda m: "{" + mapped[m.group(1)] + "}", out), list(mapped.values())

def methods(doc):
    out = []
    def walk(r, trail):
        for name, m in sorted((r.get("methods") or {}).items()):
            out.append((trail + [name], m))
        for k, x in sorted((r.get("resources") or {}).items()):
            walk(x, trail + [k])
    walk(doc, [])
    return out

ACRONYMS = {"iam": "IAM", "ssl": "SSL", "hmac": "HMAC", "ssrs": "SSRS", "ca": "CA", "oauth": "OAuth", "scim": "SCIM", "jwt": "JWT",
            "acl": "ACL", "sql": "SQL", "id": "ID", "mvu": "MVU", "entra": "Entra"}

def words(s):
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s).replace("_", " ").split()
    return " ".join(ACRONYMS.get(w.lower(), w.lower()) for w in parts)

humanize = words

NOUNS = {"Backups": "backup", "backups": "backup", "backupRuns": "backup run", "blueGreenDeployments": "blue-green deployment",
         "sslCerts": "SSL certificate", "hmacKeys": "HMAC key", "anywhereCaches": "Anywhere Cache", "rapidCaches": "Rapid Cache",
         "bucketAccessControls": "bucket ACL entry", "defaultObjectAccessControls": "default object ACL entry",
         "objectAccessControls": "object ACL entry", "managedFolders": "managed folder", "workloadCaptures": "workload capture",
         "tagBindings": "tag binding", "tagKeys": "tag key", "tagValues": "tag value", "tagHolds": "tag hold",
         "capabilityConfigs": "capability config", "capabilities": "capability", "serviceAccounts": "service account",
         "workloadIdentityPools": "workload identity pool", "workforcePools": "workforce pool", "oauthClients": "OAuth client",
         "scimTenants": "SCIM tenant", "managedIdentities": "managed identity", "namespaces": "namespace", "providers": "provider",
         "subjects": "subject", "keys": "key", "credentials": "credential", "policies": "deny policy", "connect": "connection",
         "tagBindingCollections": "tag binding collection", "liens": "lien", "users": "user", "databases": "database",
         "instances": "instance", "operations": "operation", "notifications": "notification", "folders": "folder",
         "buckets": "bucket", "objects": "object", "secrets": "secret", "versions": "version", "roles": "role",
         "projects": "project", "organizations": "organization", "tokens": "token", "iamPolicies": "IAM policy",
         "permissions": "permission"}

def singular(w):
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith(("sses", "xes", "shes", "ches")):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w

NOUNS.update({"domainmappings": "domain mapping", "workerpools": "worker pool", "workerPools": "worker pool", "nodePools": "node pool",
              "ingressRules": "firewall rule", "authorizedCertificates": "certificate", "domainMappings": "domain mapping",
              "apps": "application", "applications": "application", "xpnHost": "Shared VPC host"})

def noun_of(res, product):
    n = NOUNS.get(res) or singular(words(res))
    return (product + " " + n) if product else n

SINGLE_VERBS = {"restart", "export", "import", "clone", "failover", "destroy", "disable", "enable", "pause", "resume", "cancel",
                "relocate", "restore", "move", "rename", "demote", "switchover", "reencrypt", "undelete", "upload", "lint"}

VERB = {"delete": "Delete", "patch": "Change", "update": "Change", "setIamPolicy": "Change who can access",
        "testIamPermissions": "Test permissions on", "getIamPolicy": "Read who can access", "access": "Read the value of",
        "get": "Read"}

# Methods named verb + object (addAccessConfig): the verb's wording and the
# word that joins the object to the resource.
MULTI_VERBS = {"add": ("Add", "to"), "attach": ("Attach", "to"), "remove": ("Remove", "from"), "delete": ("Remove", "from"),
               "detach": ("Detach", "from"), "set": ("Set", "of"), "update": ("Change", "of"), "patch": ("Change", "of"),
               "get": ("Read", "of"), "list": ("List", "of"), "create": ("Create", "in"), "bulk": ("Bulk", "of"), "sign": ("Sign", "as"), "generate": ("Generate", "for")}
VERB.update({"addons": "Set the add-ons of", "legacyAbac": "Set legacy ABAC on", "locations": "Set the zones of",
             "logging": "Set logging of", "master": "Upgrade the control plane of", "monitoring": "Set monitoring of",
             "resourceLabels": "Set the labels of", "autoscaling": "Set autoscaling of", "call": "Call", "run": "Run"})

def plural(noun):
    return noun[:-1] + "ies" if noun.endswith("y") else noun + ("es" if noun.endswith(("s", "x", "sh", "ch")) else "s")

def card_of(trail, params, product):
    method = trail[-1]
    res = trail[-2] if len(trail) > 1 else trail[0]
    noun = noun_of(res, product)
    own = [p for p in params if p not in ("project", "location", "zone", "region", "apiVersion")]
    tail = " in project {project}" if ("project" in params and res != "projects") else ""
    if method in ("insert", "create"):
        # The path names the parent; the new resource's name is in the body,
        # where Compute Engine always has it.
        text = "Create " + noun
        if product == "Compute Engine":
            text += " {body.name}"
        if own:
            text += " in " + words(own[-1]) + " {" + own[-1] + "}"
    elif method == "bulkInsert":
        text = "Create " + plural(noun) + " in bulk"
    elif method == "bulkSetLabels":
        text = "Set the labels of " + plural(noun)
    elif method == "list":
        text = "List " + plural(noun)
        if own:
            text += " of " + words(own[-1]) + " {" + own[-1] + "}"
    else:
        verb = VERB.get(method)
        if verb is None:
            w = words(method).split(" ")
            first, rest = w[0], " ".join(w[1:])
            if not rest or noun.lower().endswith(rest.lower()):
                # rotateSecret on a secret: the object is the resource itself.
                plain = {"delete": "Delete", "create": "Create", "update": "Change", "patch": "Change", "get": "Read"}
                text = plain.get(first, first[0].upper() + first[1:]) + " " + noun
            else:
                v, prep = MULTI_VERBS.get(first, (first[0].upper() + first[1:], "of"))
                text = f"{v} {rest} {prep} {noun}"
        else:
            text = verb + " " + noun
        if own:
            last = own[-1]
            text += " {" + last + "}"
            if len(own) > 1 and own[0] != last:
                text += " of " + words(own[0]) + " {" + own[0] + "}"
        elif res == "projects" and "project" in params:
            text += " {project}"
    for loc in ("zone", "region"):
        if loc in params:
            text += " ({" + loc + "})"
            break
    text += tail
    return text[0].upper() + text[1:]

# Cards written by hand, by provider and method id.
CARDS = {
    ("google-cloud-bigquery", "jobs.insert"): "Run a BigQuery job in project {project}",
    ("google-cloud-bigquery", "tabledata.insertAll"): "Stream rows into BigQuery table {table} of dataset {dataset} in project {project}",
    ("google-cloud-bigquery", "rowAccessPolicies.batchDelete"): "Delete row access policies of BigQuery table {table} of dataset {dataset} in project {project}",
    ("google-cloud-bigquery", "datasets.insert"): "Create BigQuery dataset {body.datasetReference.datasetId} in project {project}",
    ("google-cloud-bigquery", "tables.insert"): "Create BigQuery table {body.tableReference.tableId} in dataset {dataset} in project {project}",
    ("google-cloud-spanner", "databases.changequorum"): "Change the quorum of Spanner database {database} of instance {instance} in project {project}",
    ("google-cloud-spanner", "databases.sessions.adapter"): "Open a protocol adapter on Spanner database {database} of instance {instance} in project {project}",
    ("google-cloud-spanner", "databases.create"): "Create Spanner database ({body.createStatement}) in instance {instance} in project {project}",
    ("google-cloud-spanner", "instances.create"): "Create Spanner instance {body.instanceId} in project {project}",
    ("google-cloud-bigquery", "jobs.query"): "Run a BigQuery query in project {project}",
    ("google-cloud-bigquery", "datasets.delete"): "Delete BigQuery dataset {dataset} in project {project}",
    ("google-cloud-bigquery", "tables.delete"): "Delete BigQuery table {table} of dataset {dataset} in project {project}",
    ("google-cloud-spanner", "databases.sessions.executeSql"): "Run SQL on Spanner database {database} of instance {instance} in project {project}",
    ("google-cloud-spanner", "databases.sessions.executeStreamingSql"): "Run SQL on Spanner database {database} of instance {instance} in project {project}",
    ("google-cloud-spanner", "databases.sessions.executeBatchDml"): "Run DML on Spanner database {database} of instance {instance} in project {project}",
    ("google-cloud-spanner", "databases.updateDdl"): "Change the schema of Spanner database {database} of instance {instance} in project {project}",
    ("google-cloud-spanner", "databases.sessions.commit"): "Commit changes to Spanner database {database} of instance {instance} in project {project}",
    ("google-cloud-spanner", "databases.dropDatabase"): "Drop Spanner database {database} of instance {instance} in project {project}",
    ("google-cloud-run", "projects.locations.services.create"): "Create Cloud Run service {query.serviceId} in project {project}",
    ("google-cloud-run", "projects.locations.jobs.create"): "Create Cloud Run job {query.jobId} in project {project}",
    ("google-cloud-run", "projects.locations.workerPools.create"): "Create Cloud Run worker pool {query.workerPoolId} in project {project}",
    ("google-cloud-run", "projects.locations.instances.create"): "Create Cloud Run instance {query.instanceId} in project {project}",
    ("google-cloud-run", "projects.locations.services.create@v1"): "Create Cloud Run service {body.metadata.name} in project {project}",
    ("google-cloud-run", "namespaces.services.create"): "Create Cloud Run service {body.metadata.name} in project {project}",
    ("google-cloud-run", "namespaces.jobs.create"): "Create Cloud Run job {body.metadata.name} in project {project}",
    ("google-cloud-run", "namespaces.workerpools.create"): "Create Cloud Run worker pool {body.metadata.name} in project {project}",
    ("google-cloud-run", "namespaces.instances.create"): "Create Cloud Run instance {body.metadata.name} in project {project}",
    ("google-cloud-run", "namespaces.domainmappings.create"): "Serve Cloud Run service {body.spec.routeName} at {body.metadata.name} in project {project}",
    ("google-cloud-run", "projects.locations.domainmappings.create"): "Serve Cloud Run service {body.spec.routeName} at {body.metadata.name} in project {project}",
    ("google-cloud-functions", "projects.locations.functions.create"): "Create Cloud Functions function {query.functionId} in project {project}",
    ("google-cloud-gke", "projects.locations.clusters.create"): "Create GKE cluster {body.cluster.name} in project {project}",
    ("google-cloud-gke", "projects.zones.clusters.create"): "Create GKE cluster {body.cluster.name} ({zone}) in project {project}",
    ("google-cloud-gke", "projects.locations.clusters.nodePools.create"): "Create GKE node pool {body.nodePool.name} in cluster {cluster} in project {project}",
    ("google-cloud-gke", "projects.zones.clusters.nodePools.create"): "Create GKE node pool {body.nodePool.name} in cluster {cluster} ({zone}) in project {project}",
    ("google-cloud-app-engine", "apps.services.versions.create"): "Deploy App Engine version {body.id} of service {service} in project {project}",
    ("google-cloud-compute", "instances.delete"): "Delete Compute Engine instance {instance} ({zone}) in project {project}, with its boot disk",
    ("google-cloud-compute", "instances.setMetadata"): "Change the metadata (startup scripts, SSH keys) of Compute Engine instance {instance} ({zone}) in project {project}",
    ("google-cloud-compute", "projects.setCommonInstanceMetadata"): "Change the metadata (startup scripts, SSH keys) of every Compute Engine VM in project {project}",
    ("google-cloud-sql", "users.delete"): "Delete database user {query.name} of Cloud SQL instance {instance} in project {project}",
    ("google-cloud-sql", "users.insert"): "Create database user {body.name} on Cloud SQL instance {instance} in project {project}",
    ("google-cloud-sql", "users.update"): "Change database user {query.name} of Cloud SQL instance {instance} in project {project}",
    ("google-cloud-sql", "instances.insert"): "Create Cloud SQL instance {body.name} in project {project}",
    ("google-cloud-sql", "databases.insert"): "Create database {body.name} on Cloud SQL instance {instance} in project {project}",
    ("google-cloud-sql", "instances.executeSql"): "Run SQL on database {body.database} of Cloud SQL instance {instance} in project {project}",
    ("google-cloud-sql", "instances.import"): "Import {body.importContext.uri} into Cloud SQL instance {instance} in project {project}",
    ("google-cloud-sql", "instances.export"): "Export Cloud SQL instance {instance} of project {project} to {body.exportContext.uri}",
    ("google-cloud-sql", "instances.clone"): "Clone Cloud SQL instance {instance} to {body.cloneContext.destinationInstanceName} in project {project}",
    ("google-cloud-sql", "instances.pointInTimeRestore"): "Restore a Cloud SQL instance to a point in time in project {project}",
    ("google-cloud-sql", "instances.restoreBackup"): "Restore a backup onto Cloud SQL instance {instance} in project {project}, replacing its data",
    ("google-cloud-sql", "instances.delete"): "Delete Cloud SQL instance {instance} in project {project} with its databases and backups",
    ("google-cloud-sql", "databases.delete"): "Delete database {database} of Cloud SQL instance {instance} in project {project}",
    ("google-cloud-storage", "objects.insert"): "Upload {query.name} to Cloud Storage bucket {bucket}",
    ("google-cloud-storage", "objects.copy"): "Copy {sourceObject} from bucket {sourceBucket} to {destinationObject} in bucket {destinationBucket}",
    ("google-cloud-storage", "objects.rewrite"): "Rewrite {sourceObject} from bucket {sourceBucket} to {destinationObject} in bucket {destinationBucket}",
    ("google-cloud-storage", "objects.compose"): "Compose {destinationObject} in Cloud Storage bucket {destinationBucket}",
    ("google-cloud-storage", "objects.move"): "Move {sourceObject} to {destinationObject} in Cloud Storage bucket {bucket}",
    ("google-cloud-storage", "objects.delete"): "Delete {object} from Cloud Storage bucket {bucket}",
    ("google-cloud-storage", "folders.deleteRecursive"): "Delete folder {folder} of Cloud Storage bucket {bucket} with everything in it",
    ("google-cloud-storage", "buckets.lockRetentionPolicy"): "Lock the retention policy of Cloud Storage bucket {bucket}",
    ("google-cloud-storage", "buckets.insert"): "Create Cloud Storage bucket {body.name} in project {query.project}",
    ("google-cloud-storage", "projects.hmacKeys.create"): "Create an HMAC key for {query.serviceAccountEmail} in project {project}",
    ("google-cloud-secret-manager", "secrets.versions.destroy"): "Destroy version {version} of secret {secret} in project {project}",
    ("google-cloud-secret-manager", "secrets.versions.access"): "Read version {version} of secret {secret} in project {project}",
    ("google-cloud-secret-manager", "secrets.addVersion"): "Store a new value for secret {secret} in project {project}",
    ("google-cloud-secret-manager", "secrets.create"): "Create secret {query.secretId} in project {project}",
    ("google-cloud-secret-manager", "secrets.delete"): "Delete secret {secret} in project {project} with every version",
    ("google-cloud-resource-manager", "projects.delete"): "Delete project {project}",
    ("google-cloud-resource-manager", "projects.create"): "Create project {body.projectId}",
    ("google-cloud-iam", "projects.serviceAccounts.keys.create"): "Create a key for service account {serviceAccount} in project {project}",
    ("google-cloud-iam", "projects.serviceAccounts.keys.upload"): "Upload a key for service account {serviceAccount} in project {project}",
    ("google-cloud-iam", "projects.serviceAccounts.create"): "Create service account {body.accountId} in project {project}",
    ("google-cloud-iam-credentials", "projects.serviceAccounts.generateAccessToken"): "Get an access token for service account {serviceAccount}",
    ("google-cloud-iam-credentials", "projects.serviceAccounts.generateIdToken"): "Get an ID token for service account {serviceAccount}",
    ("google-cloud-iam-credentials", "projects.serviceAccounts.signBlob"): "Sign data as service account {serviceAccount}",
    ("google-cloud-iam-credentials", "projects.serviceAccounts.signJwt"): "Sign a JWT as service account {serviceAccount}",
}

def classify(pid, key, trail, http):
    """Returns (class, note, when, sql) for a method, or None to leave it to the GET default."""
    method = trail[-1]
    if pid == "google-cloud-sql":
        key = {k.lower(): k for k in SQL}.get(key.lower(), key)
        if key not in SQL:
            return None if http == "GET" else ("?", None, [], None)
        c, n = SQL[key]
        when, sql = [], None
        if key in ("instances.patch", "instances.update", "instances.insert", "instances.clone"):
            when = list(SQL_SETTINGS_WHEN) if key in ("instances.patch", "instances.update") else []
            if when:
                n = ((n or "Changes the instance's settings.") + SQL_SETTINGS_NOTE)
        if key == "instances.executeSql":
            sql = ("body.sqlStatement", ["postgres", "mysql"])
        return c, n, when, sql
    if pid == "google-cloud-storage":
        if key not in STORAGE:
            return None if http == "GET" else ("?", None, [], None)
        c, n = STORAGE[key]
        when = []
        if key in ("buckets.insert", "buckets.patch", "buckets.update"):
            when, n = BUCKET_WHEN, (n or "") + BUCKET_NOTE
        elif key in ("objects.insert", "objects.patch", "objects.update"):
            when, n = ACL_WHEN("predefinedAcl") + ([("access", "{ arg: body.acl, present: true }")] if key != "objects.insert" else []), (n or "") + OBJ_ACL_NOTE
        elif key in ("objects.copy", "objects.compose", "objects.rewrite"):
            when, n = ACL_WHEN("destinationPredefinedAcl"), (n or "") + " A public predefined ACL is access."
        elif key == "managedFolders.delete":
            when, n = [("irreversible", '{ arg: query.allowNonEmpty, equals: "true" }')], n + " With allowNonEmpty it deletes the objects in it, so it is irreversible."
        return c, (n.strip() if n else None), when, None
    if pid == "google-cloud-secret-manager":
        k = key.replace("projects.locations.", "").replace("projects.", "")
        if k not in SECRETS:
            return None if http == "GET" else ("?", None, [], None)
        c, n = SECRETS[k]
        when = []
        if k == "secrets.patch":
            when = [("irreversible", "{ arg: body.expireTime, present: true }"), ("irreversible", "{ arg: body.ttl, present: true }")]
            n = "Setting an expiry (expireTime, ttl) deletes the secret with every version at that time, so it is irreversible."
        return c, n, when, None
    if pid == "google-cloud-resource-manager":
        if http == "GET":
            return None
        if method in READ_POSTS:
            return "read", "Reads; changes nothing.", [], None
        if key in CRM:
            return CRM[key] + ([], None)
        if method in ("setIamPolicy",):
            return "access", "Replaces the IAM policy: who can do what on the resource and everything under it.", [], None
        if method in ("setOrgPolicy", "clearOrgPolicy"):
            return "access", CRM_ACCESS_NOTE[method], [], None
        if trail[0] in ("tagKeys", "tagValues", "tagBindings") or "tagBinding" in key:
            return "access", CRM_ACCESS_NOTE["tag"], [], None
        if "boundaries" in trail or method == "updateBoundaryConfig":
            return "access", ("Boundaries group projects by their tags under a management project, as tags feed IAM and "
                              "organization policy conditions; counted as access like tags."), [], None
        if "capabilit" in key.lower():
            return ("delete" if method == "delete" else "write"), None, [], None
        return "?", None, [], None
    if pid == "google-cloud-iam":
        if http == "GET":
            return None
        if method in READ_POSTS:
            return "read", "Reads; changes nothing.", [], None
        if key in IAM_CRED:
            return "credential", IAM_CRED[key], [], None
        return "access", "Identities, roles and their keys decide who can do what in the project.", [], None
    if pid == "google-cloud-iam-credentials":
        if http == "GET":
            return None
        return "credential", IAMCRED_NOTES.get(key), [], None
    if pid == "google-cloud-compute":
        if http == "GET":
            return None
        base, table = compute_base(trail[0]), COMPUTE.get(compute_base(trail[0]))
        if table is None:
            return ("?", None, [], None)
        if method in table:
            c, n = table[method]
        elif method in COMPUTE_METHOD:
            c, n = COMPUTE_METHOD[method]
        elif "*" in table:
            c, n = table["*"]
        else:
            return ("?", None, [], None)
        when = []
        if f"{base}.{method}" in COMPUTE_WHEN:
            when, extra = COMPUTE_WHEN[f"{base}.{method}"]
            n = (n + " " if n else "") + extra
        return c, n, when, None
    if pid == "google-cloud-gke":
        k = key.replace("projects.locations.", "").replace("projects.zones.", "")
        if http == "GET":
            if trail[-2] == "clusters" and method in ("get", "list"):
                return ("credential", "Clusters made with basic auth or a client certificate return the password and the certificate's private key; "
                        "the proxy redacts them.", [], None)
            return None
        if k not in GKE:
            return ("?", None, [], None)
        c, n = GKE[k]
        when = []
        if k == "clusters.update":
            fields = CURRENT["doc"]["schemas"]["ClusterUpdate"]["properties"]
            for f in GKE_ACCESS_FIELDS + ["desiredNodePoolAutoscaling", "desiredLocations"]:
                assert f in fields, f  # a condition on a field the API does not have would never hold
            when = [("access", f"{{ arg: body.update.{f}, present: true }}") for f in GKE_ACCESS_FIELDS]
            when += [("money", "{ arg: body.update.desiredNodePoolAutoscaling, present: true }"),
                     ("money", "{ arg: body.update.desiredLocations, present: true }")]
            n = ("Opening the control plane or the nodes to networks, and changing who can authenticate, which bindings RBAC allows, "
                 "what images may run or the nodes' network tags, are access; node autoscaling and zones are money.")
        return c, n, when, None
    if pid == "google-cloud-run":
        if http == "GET":
            return ("credential", RUN_ENV_NOTE, [], None) if bearing(CURRENT["doc"], CURRENT["m"], {"env"}) else None
        got = run_classify(key, trail, http)
        if got is None:
            return ("?", None, [], None)
        c, n, when = got
        if when:
            n = (n + " " if n else "") + RUN_OVERRIDES
        return c, n, when, None
    if pid == "google-cloud-functions":
        if http == "GET":
            return (("credential", "Returns the function's environment variables. The proxy holds their values: the agent sees tokens, "
                     "which a write of the same function may carry back.", [], None) if bearing(CURRENT["doc"], CURRENT["m"], FN_PROPS) else None)
        if method in FN:
            return FN[method] + ([], None)
        if "Upgrade" in method or method == "detachFunction":
            return "write", None, [], None
        return ("?", None, [], None)
    if pid == "google-cloud-app-engine":
        if http == "GET":
            return (("credential", "With view=FULL, returns the version's environment variables. The proxy holds their values.", [], None)
                    if bearing(CURRENT["doc"], CURRENT["m"], GAE_PROPS) else None)
        k = key.replace("projects.locations.applications.", "").replace("apps.", "", 1)
        for prefix, name in (("authorizedCertificates.", "authorizedCertificates"), ("firewall.ingressRules.", "ingressRules")):
            if k.startswith(prefix):
                return GAE[name] + ([], None)
        k = k.replace("services.versions.instances.", "instances.").replace("services.versions.", "versions.")
        if k in GAE:
            return GAE[k] + ([], None)
        return ("?", None, [], None)
    if pid == "google-cloud-bigquery":
        if http == "GET":
            return None
        if key == "jobs.insert":
            return "unknown", BQ_JOB_NOTE, BQ_JOB_WHEN, ("body.configuration.query.query", ["googlesql"])
        if key == "jobs.query":
            return ("unknown", "The class comes from the SQL, read as GoogleSQL (legacy SQL cannot change data); a continuous "
                    "query runs, and is billed, until it is stopped.",
                    [("money", '{ arg: body.continuous, equals: "true" }')], ("body.query", ["googlesql"]))
        if method == "setIamPolicy":
            return "access", "Decides who can read and change the resource.", [], None
        if method in ("getIamPolicy", "testIamPermissions"):
            return "read", "Reads; changes nothing.", [], None
        if trail[0] == "rowAccessPolicies":
            return "access", "Row access policies decide who can read which rows.", [], None
        if key in BQ:
            return BQ[key][0], BQ[key][1], BQ[key][2], None
        return ("?", None, [], None)
    if pid == "google-cloud-spanner":
        if http == "GET":
            return None
        k = ckey_of(pid, key)
        if method == "setIamPolicy":
            return "access", "Decides who can read and change the resource.", [], None
        if method in ("getIamPolicy", "testIamPermissions"):
            return "read", "Reads; changes nothing.", [], None
        if trail[-2] == "operations":
            return "write", None, [], None
        if k in SPANNER_SQL_RULES:
            arg, c = SPANNER_SQL_RULES[k]
            return c, SPANNER_SQL, [], (arg, ["googlesql", "postgres"])
        if k in SPANNER:
            return SPANNER[k] + (None,)
        return ("?", None, [], None)
    if pid in T27C:
        k = ckey_of(pid, key)
        if http == "GET":
            got = T27C_GET.get((pid, k))
            return (got[0], got[1], [], None) if got else None
        t = T27C[pid]
        if k in t:
            return t[k] + (None,)
        if method == "setIamPolicy":
            return "access", "Decides who can read and change the resource.", [], None
        if method in ("getIamPolicy", "testIamPermissions"):
            return "read", "Reads; changes nothing.", [], None
        if len(trail) > 1 and trail[-2] == "operations":
            return {"cancel": ("write", None, [], None), "delete": ("write", "Deletes the record of an operation, not what it did.", [], None)}.get(method, ("?", None, [], None))
        return ("?", None, [], None)
    raise ValueError(pid)

FN_PROPS = {"environmentVariables", "buildEnvironmentVariables"}
GAE_PROPS = {"envVariables", "buildEnvVariables"}
ENV_PROPS = {"google-cloud-run": {"env"}, "google-cloud-functions": FN_PROPS, "google-cloud-app-engine": GAE_PROPS}
CURRENT = {}

def schema_has(doc, name, props, seen=None):
    """Whether schema name has, at any depth, a property in props."""
    seen = seen if seen is not None else set()
    if not name or name in seen:
        return False
    seen.add(name)
    sch = doc.get("schemas", {}).get(name)
    if not sch:
        return False
    def walk(node):
        if not isinstance(node, dict):
            return False
        if "$ref" in node:
            return schema_has(doc, node["$ref"], props, seen)
        for k, v in (node.get("properties") or {}).items():
            if k in props or walk(v):
                return True
        return walk(node.get("items")) or walk(node.get("additionalProperties"))
    return walk(sch)

def bearing(doc, m, props):
    """Whether a method's response can carry environment values: the resource, or a long-running operation."""
    ref = (m.get("response") or {}).get("$ref", "")
    return "Operation" in ref or schema_has(doc, ref, props)

def env_patterns(pid, doc):
    present = set()
    for sch in doc.get("schemas", {}).values():
        present |= set((sch.get("properties") or {}).keys())
    if pid == "google-cloud-run":
        return [RUN_ENV]
    return ["**." + p for p in sorted(ENV_PROPS[pid]) if p in present]

def example_response(pid, doc):
    """A response with a value at every path the rule's transform names, in the API's own shape."""
    if pid == "google-cloud-gke":
        return {"name": "orders-cluster", "masterAuth": {"username": "admin", "password": "example-password",
                "clientKey": "LS0tLS1CRUdJTiBFWEFNUExFIEtFWS0tLS0t", "clusterCaCertificate": "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0t"}}
    if pid == "google-cloud-run":
        return {"name": "orders-api", "template": {"containers": [{"image": "us-docker.pkg.dev/acme-prod/web/orders:1",
                "env": [{"name": "DB_PASSWORD", "value": "example-secret-value"}, {"name": "PORT", "value": "8080"}]}]}}
    pats = env_patterns(pid, doc)
    out = {"name": "example"}
    for i, p in enumerate(pats):
        out[p[3:]] = {"API_KEY": f"example-secret-value-{i + 1}"}
    return out

def ckey_of(pid, key):
    if pid == "google-cloud-spanner":
        k = key.replace("projects.", "", 1)
        return k[len("instances."):] if k.startswith("instances.") and k.count(".") > 1 else k
    if pid in T27C:
        for prefix in ("projects.locations.", "projects.instances.", "projects."):
            if key.startswith(prefix):
                return key[len(prefix):]
    return key

def transform_of(pid, key, trail, http, m, doc, cls):
    """Returns (response transform, restore paths) for a rule, or Nones."""
    method = trail[-1]
    if pid == "google-cloud-gke":
        if http == "GET" and cls == "credential":
            return {"redact": GKE_SECRET_PATHS, "class": "read"}, None
        return None, None
    if pid not in ENV_PROPS:
        return None, None
    pats = env_patterns(pid, doc)
    if http == "GET" or cls == "credential":
        return ({"hold": pats, "class": "read"}, None) if cls == "credential" else (None, None)
    if cls == "read" or method in ("setIamPolicy", "testIamPermissions") or not bearing(doc, m, ENV_PROPS[pid]):
        return None, None
    restore = pats if ((pid == "google-cloud-run" and (http == "PUT" or method == "patch")) or
                       (pid == "google-cloud-functions" and method == "patch")) else None
    return {"hold": pats, "class": cls}, restore

SAMPLE = {"apiVersion": "v1", "zone": "us-central1-a", "region": "us-central1", "cluster": "orders-cluster", "nodePool": "default-pool",
          "service": "orders-api", "function": "send-email", "job": "nightly-export", "project": "acme-prod", "location": "us-central1", "instance": "orders-db", "database": "orders", "bucket": "acme-uploads",
          "object": "reports%2F2026.csv", "secret": "stripe-key", "version": "3", "serviceAccount": "deployer@acme-prod.iam.gserviceaccount.com",
          "folder": "123456789012", "organization": "987654321098"}

def sample(p):
    return SAMPLE.get(p, p.lower() + "-1")

def wrap(text, indent="      "):
    out, line = [], indent
    for w in text.split():
        if len(line) + len(w) + 1 > 100 and line.strip():
            out.append(line); line = indent
        line += ("" if line.strip() == "" else " ") + w
    out.append(line)
    return out

FS_DOC = "/v1/projects/{project}/databases/{database}/documents/{collection}/{document}/{path*}"
EXTRA = {  # rules for paths the discovery documents do not list
    "google-cloud-firestore": [
        ("documents.delete-nested", "DELETE", FS_DOC, "irreversible", "Delete Firestore document {collection}/{document}/{path} in database {database} of project {project}",
         "A deleted document is gone, unless point-in-time recovery is on, which Opfence cannot see.",
         "The discovery document's flat paths cover only top-level collections; this covers subcollections at any depth."),
        ("documents.patch-nested", "PATCH", FS_DOC, "write", "Change Firestore document {collection}/{document}/{path} in database {database} of project {project}",
         "Updates the document, or creates it.",
         "The discovery document's flat paths cover only top-level collections; this covers subcollections at any depth."),
        ("documents.create-nested", "POST", FS_DOC, "write", "Create a Firestore document in {collection}/{document}/{path} in database {database} of project {project}",
         "Creates a document. A query or listing in a subcollection matches this rule too, and counts as a write.",
         "The discovery document's flat paths cover only top-level collections; this covers subcollections at any depth."),
    ],
    "google-cloud-storage": [
        ("uploads.continue", "PUT", "/upload/storage/v1/b/{bucket}/o", "write", "Continue uploading an object to bucket {bucket}",
         "A resumable upload sends its data to the session URI the first request returned, with PUT.",
         "Later requests of a resumable upload; the discovery document lists only the first."),
        ("uploads.cancel", "DELETE", "/upload/storage/v1/b/{bucket}/o", "write", "Cancel an upload to bucket {bucket}", "Drops only the data uploaded so far.",
         "Cancels a resumable upload; not listed in the discovery document."),
    ],
}

BATCH_DELETE = """# description: Delete two objects of Cloud Storage bucket acme-uploads in one batch
POST /batch/storage/v1 HTTP/1.1
Host: storage.googleapis.com
Authorization: Bearer opf_EXAMPLE_google_access_token
Content-Type: multipart/mixed; boundary="===============0815==="

--===============0815===
Content-Type: application/http
MIME-Version: 1.0
Content-Transfer-Encoding: binary
Content-ID: <0815+1>

GET /storage/v1/b/acme-uploads/o/reports%2F2026.csv HTTP/1.1
Content-Type: application/json
MIME-Version: 1.0
Host: storage.googleapis.com

--===============0815===
Content-Type: application/http
MIME-Version: 1.0
Content-Transfer-Encoding: binary
Content-ID: <0815+2>

DELETE /storage/v1/b/acme-uploads/o/reports%2F2025.csv HTTP/1.1
Content-Type: application/json
MIME-Version: 1.0
Host: storage.googleapis.com

--===============0815===--
"""
# Extra fixtures for a rule, by provider and method id: (file, body, expected class).
EXTRA_TESTS = {
    ("google-cloud-bigquery", "jobs.insert"): [
        ("jobs-insert-destination-drop.http", """# description: Run a BigQuery job in project acme-prod: its SQL drops a table while its results go to another
POST /bigquery/v2/projects/acme-prod/jobs HTTP/1.1
Host: bigquery.googleapis.com
Authorization: Bearer opf_EXAMPLE_google_access_token
Content-Type: application/json

{"configuration": {"query": {"query": "DROP TABLE sales.orders", "useLegacySql": false, "destinationTable": {"projectId": "acme-prod", "datasetId": "sales", "tableId": "copy"}}}}
""", "irreversible"),
        ("jobs-insert-script.http", """# description: Run a BigQuery job in project acme-prod: a script with control flow
POST /bigquery/v2/projects/acme-prod/jobs HTTP/1.1
Host: bigquery.googleapis.com
Authorization: Bearer opf_EXAMPLE_google_access_token
Content-Type: application/json

{"configuration": {"query": {"query": "IF TRUE THEN DELETE FROM sales.orders WHERE true; END IF", "useLegacySql": false}}}
""", "unknown")],
    ("google-cloud-storage", "objects.delete"): [("objects-delete-batch.http", BATCH_DELETE, "irreversible")],
}

summary = []
NEW_IDS = {"compute", "container", "run", "cloudfunctions", "appengine", "bigquery", "spanner", "firestore", "datastore",
           "pubsub", "redis", "bigtableadmin", "dns", "cloudkms"}
ID_SKIP = {"projects", "locations", "namespaces", "apps", "applications", "zones", "aggregated"}
ONLY = set(sys.argv[2:])  # provider ids to write; all when empty
for prov in P:
    pid = prov["id"]
    if ONLY and pid not in ONLY:
        continue
    D = f"catalog/{pid}/"
    os.makedirs(D + "fixtures", exist_ok=True)
    for f in os.listdir(D + "fixtures"):
        os.remove(D + "fixtures/" + f)
    for f in os.listdir(D):
        if f.endswith(".yaml"):
            os.remove(D + f)
    hosts = prov["hosts"]
    schemas = []
    files, ids, unknown, nrules, nfix = {}, set(), [], 0, 0
    for api, version, suffix in prov["versions"]:
        doc = load(api, version)
        schemas.append(DISCOVERY.format(api=api, version=version))
        base = "/" + (doc.get("servicePath") or "").strip("/")
        base = base.rstrip("/")
        for trail, m in methods(doc):
            key = m["id"].split(".", 1)[1]
            http = m["httpMethod"]
            CURRENT["doc"], CURRENT["m"], CURRENT["pid"] = doc, m, pid
            got = classify(pid, key, trail, http)
            if got is None:
                continue
            cls, note, when, sql = got
            if cls == "?":
                unknown.append(f"{api}/{version} {key}")
                continue
            paths = [(base + "/" + (m.get("flatPath") or m["path"]).lstrip("/"), "")]
            if prov.get("version_param"):
                old, new = prov["version_param"]
                assert paths[0][0].startswith(old), paths[0][0]
                paths = [(new + paths[0][0][len(old):], "")]
            xform, restore = transform_of(pid, key, trail, http, m, doc, cls)
            up = (m.get("mediaUpload") or {}).get("protocols") or {}
            for kind in ("simple", "resumable"):
                if up.get(kind, {}).get("path"):
                    upath = "/" + up[kind]["path"].lstrip("/")
                    if "{+" in upath and m.get("flatPath") and upath.endswith(m["path"]):
                        # /upload/v2/{+parent}:uploadSource, with the flat path's parameters
                        upath = upath[:len(upath) - len(m["path"])] + m["flatPath"]
                    paths.append((upath, "-upload" if kind == "simple" else "-resumable"))
            for raw, psuffix in paths:
                tmpl, params = template(raw)
                if prov.get("versions")[0][0] in NEW_IDS:
                    skip = ID_SKIP | set(prov.get("id_skip", []))
                    rest = [t for t in trail[:-1] if t not in skip] or [trail[-2] if prov.get("id_skip") and len(trail) > 1 else trail[0]]
                    dash = lambda t: humanize(t).lower().replace(" ", "-")
                    group = dash(rest[0])
                    rid = f"{pid}.{group}." + "-".join(dash(t) for t in rest[1:] + [trail[-1]])
                    if suffix:
                        rid += "-" + suffix
                    rid += psuffix
                    if rid in ids:
                        rid += "-by-zone" if "zones" in trail else "-by-location" if ("locations" in trail or "applications" in trail) else ""
                    if rid in ids:
                        rid += "-" + http.lower()
                else:
                    group = trail[0] if trail[0] not in ("projects", "locations", "organizations") or len(trail) == 2 else trail[1] if len(trail) > 2 else trail[0]
                    group = humanize(group).lower().replace(" ", "-")
                    verb = "-".join(humanize(t).lower().replace(" ", "-") for t in (trail[1:] if trail[0] in ("projects", "locations") and len(trail) > 2 else trail))
                    rid = f"{pid}.{group}.{verb}" if not verb.startswith(group + "-") else f"{pid}.{group}.{verb[len(group)+1:]}"
                    if suffix:
                        rid += "-" + suffix
                    rid += psuffix
                    if rid in ids:
                        rid += "-" + http.lower()
                assert rid not in ids, rid
                ids.add(rid)
                res = "project" if "project" in params else ("bucket" if "bucket" in params else (params[0] if params else None))
                if res is None and pid == "google-cloud-storage" and key in ("buckets.insert",):
                    res = "query.project"
                ckey = ckey_of(pid, key)
                if pid == "google-cloud-secret-manager":
                    ckey = key.replace("projects.locations.", "").replace("projects.", "")
                ctrail = trail
                if pid == "google-cloud-compute":
                    ctrail = [compute_base(trail[0])] + trail[1:]
                card = CARDS.get((pid, ckey + "@" + version)) or CARDS.get((pid, ckey)) or card_of(ctrail, params, prov["product"])
                L = files.setdefault(group, [f"# {prov['title']}: {group.replace('-', ' ')}.",
                                             "# Generated from Google's discovery documents (see provider.yaml); classes reviewed by hand.",
                                             "operations:"])
                L.append(f"  - id: {rid}")
                L.append(f"    match: {{ rest: {{ method: {http}, path: \"{tmpl}\" }} }}")
                L.append(f"    class: {cls}")
                if when:
                    L.append("    when:")
                    for wc, cond in when:
                        L += [f"      - if: {cond}", f"        class: {wc}"]
                if sql:
                    L.append(f"    classify: {{ sql: {sql[0]}, dialect: [{', '.join(sql[1])}] }}")
                if xform:
                    parts = ", ".join(f"{k}: {json.dumps(v) if isinstance(v, list) else v}" for k, v in xform.items())
                    L.append(f"    response: {{ {parts} }}")
                if restore:
                    L.append(f"    restore: {json.dumps(restore)}")
                if res:
                    kind = {"project": "project", "bucket": "bucket", "query.project": "project"}.get(res, res)
                    L.append(f"    resource: {{ arg: {res}, kind: {kind} }}")
                if cls != "read" or sql:
                    L.append(f"    card: {json.dumps(card)}")
                L += ["    status: verified", f"    verified: {prov.get('verified', '2026-10-24')}", "    sources:", f"      - {DISCOVERY.format(api=api, version=version)}"]
                n = note or ""
                if m.get("deprecated"):
                    n = (n + " " if n else "") + "Google has deprecated this method."
                if n.strip():
                    L.append("    notes: >-")
                    L += wrap(n.strip())
                # Fixtures: the base case, and one for each condition.
                host = hosts[0]
                def fpath(t, extra_q=""):
                    return re.sub(r"\{([A-Za-z0-9_]+)\*?\}", lambda mm: sample(mm.group(1)), t) + extra_q
                base_q = "?project=acme-prod" if res == "query.project" else ""
                bodyless = http in ("GET", "DELETE")
                body = {}
                sample_sql = SQL_SAMPLES.get((pid, ckey_of(pid, key))) or SQL_SAMPLES.get((pid, "*"))
                if sql:
                    body = sample_sql[0][0]
                fname = rid.split(".", 1)[1].replace(".", "-")
                tests = []
                desc = re.sub(r"\{([A-Za-z0-9_.]+)\}", lambda mm: {"body.name": "acme-uploads", "query.project": "acme-prod"}.get(mm.group(1), sample(mm.group(1))), card)
                def write_fixture(name, q, b, d):
                    lines = [f"# description: {d}", f"{http} {fpath(tmpl, q)} HTTP/1.1", f"Host: {host.replace('*', 'us-central1')}", "Authorization: Bearer opf_EXAMPLE_google_access_token"]
                    if not bodyless:
                        lines += ["Content-Type: application/json", "", json.dumps(b)]
                    else:
                        lines.append("")
                    open(D + "fixtures/" + name, "w").write("\n".join(lines) + "\n")
                base_body = {"name": "acme-uploads"} if key == "buckets.insert" else body
                write_fixture(fname + ".http", base_q, base_body, desc)
                tests.append((fname + ".http", sample_sql[0][1] if sql else cls))
                if sql:
                    write_fixture(fname + "-drop.http", base_q, sample_sql[1][0], desc + (": drop a table" if pid == "google-cloud-sql" else ": change every row or drop a table"))
                    tests.append((fname + "-drop.http", sample_sql[1][1]))
                for i, (wc, cond) in enumerate(when):
                    mm = re.match(r"\{ arg: (query|body)\.([A-Za-z0-9_.]+), (present: true|equals: \"([^\"]*)\"|matches: .*) \}", cond)
                    where, field, test, eq = mm.group(1), mm.group(2), mm.group(3), mm.group(4)
                    val = eq if eq is not None else ("publicRead" if test.startswith("matches") else {"lifecycle": {"rule": []}}.get(field, ["10.0.0.0/8"] if "Networks" in field else "x"))
                    if where == "query":
                        q = (base_q + "&" if base_q else "?") + f"{field}={val}"
                        b = base_body
                    else:
                        q = base_q
                        b = json.loads(json.dumps(base_body))
                        cur = b
                        parts = field.split(".")
                        for p_ in parts[:-1]:
                            cur = cur.setdefault(p_, {})
                        if eq is not None:
                            cur[parts[-1]] = {"true": True, "false": False}.get(eq, eq)
                        else:
                            cur[parts[-1]] = val
                    name = f"{fname}-when{i + 1}.http"
                    write_fixture(name, q, b, desc + f" ({field})")
                    tests.append((name, wc))
                for xname, xbody, xexpect in (EXTRA_TESTS.get((pid, key), []) if not psuffix else []):
                    open(D + "fixtures/" + xname, "w").write(xbody)
                    tests.append((xname, xexpect))
                L.append("    tests:")
                for ti, (f_, e_) in enumerate(tests):
                    L += [f"      - fixture: fixtures/{f_}", f"        expect: {e_}"]
                    if xform and ti == 0:
                        rname = fname + ".json"
                        open(D + "fixtures/" + rname, "w").write(json.dumps(example_response(pid, doc), indent=2) + "\n")
                        L.append(f"        response: fixtures/{rname}")
                    if res:
                        rv = {"query.project": "acme-prod"}.get(res, sample(res).replace("%2F", "/"))
                        L.append(f"        resource: \"{rv}\"")
                    nfix += 1
                L.append("")
                nrules += 1
    for (rid_s, http, tmpl, cls, card, note, why) in EXTRA.get(pid, []):
        rid = f"{pid}.{rid_s}"
        g = rid_s.split(".")[0]
        L = files.setdefault(g, [f"# {prov['title']}: {g}.", "operations:"])
        params = re.findall(r"\{([A-Za-z0-9_]+)\*?\}", tmpl)
        L += [f"  - id: {rid}", f"    match: {{ rest: {{ method: {http}, path: \"{tmpl}\" }} }}", f"    class: {cls}"]
        if params:
            L.append(f"    resource: {{ arg: {params[0]}, kind: {params[0]} }}")
        L += [f"    card: {json.dumps(card)}", f"    unlisted: {json.dumps(why)}", "    status: verified", f"    verified: {prov.get('verified', '2026-10-24')}",
              "    sources:", f"      - {prov['docs']}", "    notes: >-"] + wrap(note)
        fname = rid_s.replace(".", "-") + ".http"
        p = re.sub(r"\{([A-Za-z0-9_]+)\*?\}", lambda mm: sample(mm.group(1)), tmpl)
        q = "?uploadType=resumable&upload_id=ADPycd123" if g == "uploads" else ""
        p = p.replace("/collection-1/document-1/path-1", "/users/alice/orders/o-1")
        cdesc = re.sub(r'{([A-Za-z0-9_]+)}', lambda mm: sample(mm.group(1)), card).replace("collection-1/document-1/path-1", "users/alice/orders/o-1")
        lines = [f"# description: {cdesc}", f"{http} {p}{q} HTTP/1.1", f"Host: {hosts[0]}",
                 "Authorization: Bearer opf_EXAMPLE_google_access_token", ""]
        open(D + "fixtures/" + fname, "w").write("\n".join(lines) + "\n")
        L += ["    tests:", f"      - fixture: fixtures/{fname}", f"        expect: {cls}"]
        if params:
            L.append(f"        resource: \"{sample(params[0])}\"")
        L.append("")
        nrules += 1; nfix += 1
    for g, L in files.items():
        open(D + g + ".yaml", "w").write("\n".join(L))
    host_lines = ", ".join(f'"{h}"' if "*" in h else h for h in hosts)
    prov_yaml = [f"provider: {pid}", f"title: {prov['title']}", f"docs: {prov['docs']}"]
    prov_yaml += ["# " + l for l in wrap(prov["about"], "")]
    prov_yaml += ["# Generated from Google's discovery documents; every method that is not a",
                  "# GET has a rule, and so do the GETs that return secrets. The bearer token",
                  "# is a short-lived OAuth access token that google-oauth mints, so the agent",
                  "# holds a placeholder the proxy swaps in here (secrets_from).",
                  f"hosts: [{host_lines}]"] + ([f"batch: [{', '.join(prov['batch'])}]"] if prov.get("batch") else []) + [
                  "auth:", "  - header: Authorization", "    scheme: Bearer", "secrets_from: [google-oauth]",
                  "defaults:", "  rest_safe_methods: read", "schemas:"]
    for s in schemas:
        prov_yaml += ["  - kind: discovery", f"    url: {s}"]
    open(D + "provider.yaml", "w").write("\n".join(prov_yaml) + "\n")
    summary.append(f"{pid}: {nrules} rules, {nfix} fixtures, {len(files)} files")
    if unknown:
        print("UNCLASSIFIED", pid, unknown)
print("\n".join(summary))
