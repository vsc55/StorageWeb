EAPI=8

inherit acct-user

DESCRIPTION="Usuario del servicio StorageWeb"
ACCT_USER_ID=-1
ACCT_USER_GROUPS=( storageweb )
ACCT_USER_HOME=/var/lib/storageweb
ACCT_USER_HOME_PERMS=0750

acct-user_add_deps
