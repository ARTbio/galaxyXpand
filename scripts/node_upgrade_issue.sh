# 1. Supprimer le dossier contenant les modules globaux de Node dans le venv
rm -rf /home/galaxy/galaxy/.venv/lib/node_modules

# 2. Supprimer tous les exécutables liés à Node dans le dossier bin
rm -f /home/galaxy/galaxy/.venv/bin/node
rm -f /home/galaxy/galaxy/.venv/bin/npm
rm -f /home/galaxy/galaxy/.venv/bin/npx
rm -f /home/galaxy/galaxy/.venv/bin/corepack

# in case of error due to pre-existing node during 24.1 to 25.1 upgrade:
# TASK [galaxyproject.galaxy : Install or upgrade node] *********************************************************************************************************************************************************************************************************************
# fatal: [localhost]: FAILED! =>
#     changed: true
#     cmd:
#     - nodeenv
#     - -n
#     - 22.13.0
#     - -p
#     delta: '0:00:03.114150'
#     end: '2025-12-19 13:17:27.075784'
#     msg: non-zero return code
#     rc: 1
#     start: '2025-12-19 13:17:23.961634'
#     stderr: |-
#         /home/galaxy/galaxy/.venv/lib/python3.12/site-packages/nodeenv.py:48: UserWarning: pkg_resources is deprecated as an API. See https://setuptools.pypa.io/en/latest/pkg_resources.html. The pkg_resources package is slated for removal as early as 2025-11-30. Refrain from using this package or pin to Setuptools<81.
#           from pkg_resources import parse_version
#          * Install prebuilt node (22.13.0) ....
#         Traceback (most recent call last):
#           File "/home/galaxy/galaxy/.venv/lib/python3.12/site-packages/nodeenv.py", line 652, in copytree
#             shutil.copytree(s, d, symlinks, ignore)
#           File "/usr/lib/python3.12/shutil.py", line 600, in copytree
#             return _copytree(entries=entries, src=src, dst=dst, symlinks=symlinks,
#                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#           File "/usr/lib/python3.12/shutil.py", line 498, in _copytree
#             os.makedirs(dst, exist_ok=dirs_exist_ok)
#           File "<frozen os>", line 225, in makedirs
#         FileExistsError: [Errno 17] File exists: '/home/galaxy/galaxy/.venv/bin'

#         During handling of the above exception, another exception occurred:

#         Traceback (most recent call last):
#           File "/home/galaxy/galaxy/.venv/bin/nodeenv", line 7, in <module>
#             sys.exit(main())
#                      ^^^^^^
#           File "/home/galaxy/galaxy/.venv/lib/python3.12/site-packages/nodeenv.py", line 1122, in main
#             create_environment(env_dir, args)
#           File "/home/galaxy/galaxy/.venv/lib/python3.12/site-packages/nodeenv.py", line 998, in create_environment
#             install_node(env_dir, src_dir, args)
#           File "/home/galaxy/galaxy/.venv/lib/python3.12/site-packages/nodeenv.py", line 755, in install_node
#             install_node_wrapped(env_dir, src_dir, args)
#           File "/home/galaxy/galaxy/.venv/lib/python3.12/site-packages/nodeenv.py", line 790, in install_node_wrapped
#             copy_node_from_prebuilt(env_dir, src_dir, args.node)
#           File "/home/galaxy/galaxy/.venv/lib/python3.12/site-packages/nodeenv.py", line 682, in copy_node_from_prebuilt
#             copytree(src_folder, dest, True)
#           File "/home/galaxy/galaxy/.venv/lib/python3.12/site-packages/nodeenv.py", line 654, in copytree
#             copytree(s, d, symlinks, ignore)
#           File "/home/galaxy/galaxy/.venv/lib/python3.12/site-packages/nodeenv.py", line 659, in copytree
#             os.symlink(os.readlink(s), d)
#         FileExistsError: [Errno 17] File exists: '../lib/node_modules/npm/bin/npx-cli.js' -> '/home/galaxy/galaxy/.venv/bin/npx'
#     stderr_lines: <omitted>
#     stdout: ''
#     stdout_lines: <omitted>

# PLAY RECAP ****************************************************************************************************************************************************************************************************************************************************************
# localhost                  : ok=88   changed=12   unreachable=0    failed=1    skipped=51   rescued=0    ignored=0