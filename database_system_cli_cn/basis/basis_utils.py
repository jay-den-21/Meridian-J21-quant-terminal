"""Compatibility surface for the removed machine-bound registration module."""

from basis.errors import legacy_authorization_removed


def get_webservertime():
    legacy_authorization_removed("basis.basis_utils.get_webservertime")


def check_regist():
    legacy_authorization_removed("basis.basis_utils.check_regist")


class register:
    def __init__(self):
        legacy_authorization_removed("basis.basis_utils.register")

    def get_serial_number(self):
        legacy_authorization_removed("basis.basis_utils.register.get_serial_number")

    def get_mac_address(self):
        legacy_authorization_removed("basis.basis_utils.register.get_mac_address")

    def get_mac_address_like_cpu_id(self):
        legacy_authorization_removed(
            "basis.basis_utils.register.get_mac_address_like_cpu_id"
        )

    def get_cpu_sn(self):
        legacy_authorization_removed("basis.basis_utils.register.get_cpu_sn")

    def Des_Encrypt(self, O0O0O00000O00O0OO):
        legacy_authorization_removed("basis.basis_utils.register.Des_Encrypt")

    def Des_Decrypt(self, O0OOOO00O0000OO00):
        legacy_authorization_removed("basis.basis_utils.register.Des_Decrypt")

    def get_authorized_code(self, O0O0O000OO00OOOOO):
        legacy_authorization_removed(
            "basis.basis_utils.register.get_authorized_code"
        )

    def get_authorized_code_by_machine_and_exp_date(
        self, OOOOOO0OO0OOO0OOO, OOO0OOO0000OO00O0
    ):
        legacy_authorization_removed(
            "basis.basis_utils.register.get_authorized_code_by_machine_and_exp_date"
        )

    def check_authorization(self):
        legacy_authorization_removed(
            "basis.basis_utils.register.check_authorization"
        )

    def regist(self):
        legacy_authorization_removed("basis.basis_utils.register.regist")
