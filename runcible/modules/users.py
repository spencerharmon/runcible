from runcible.modules.module_array import ModuleArray
from runcible.modules.user import User


class Users(ModuleArray):
    module_name = 'users'
    sub_module = User
    sort_key = 'name'
