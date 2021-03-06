# MIT License

# Copyright (c) 2017 Rebecca ".bx" Shapiro

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os


def bbxmqemu(main, target_config,
             stages,
             policies,
             hw_config,
             host_software_config,
             instance_id,
             test_id,
             data_root,
             is_watchpoint,
             quick):
    qemu = os.path.join(host_software_config.root, host_software_config.binary)
    cmds = []
    run_cmd = "%s -gdb stdio -M %s -sd %s -clock vm " \
              "-S" % (qemu, hw_config.machinename,
                       main.get_config('sd_image'))

    deps = []
    targets = []
    main_cfgs = {}
    if is_watchpoint:
        if len(stages) == 1:
            s = stages[0]
            f = os.path.join(data_root, "trace-events-%s.raw" % s.stagename)
            main_cfgs["trace_events_output"] = f
            d = os.path.join(data_root, "trace-events-%s.completed" % s.stagename)
            targets = [f]
            n = main.get_config("trace_events_file", s)
            deps = [n]
            run_cmd += " -trace events=%s,file=%s" % (n, f)

    cfg = {'gdb_commands': ["set tcp connect-timeout 120", "set remotetimeout -1",
                            "target extended-remote | exec %s" % (run_cmd)]}
    if not is_watchpoint:
        gdb_tools = os.path.join(main.test_suite_dir, "gdb_tools.py")
        cfg['gdb_commands'].append('mon trace-event main_uboot_writes off')
        cfg['gdb_commands'].append('mon  trace-event my_cpu_write off')
        cfg['gdb_commands'].append('mon  trace-file off')
        cfg['gdb_commands'].append('python execfile(\"%s\")' % gdb_tools)
    main_cfgs["is_bare_metal"] = False
    deps.append(qemu)
    ret = cmds + [('configs', cfg), ("set_config", main_cfgs),
                  ('file_dep', deps), ("targets", targets)]
    return ret


def breakpoint(main, configs,
               stages,
               policies,
               hw_config,
               instance_id,
               test_id,
               data_root,
               quick):
    gdb_deps = []
    done_targets = []
    gdb_targets = []
    done_commands = []
    main_cfgs = {}
    trace_dbs = {}
    gdb_cmds = []
    deps = []
    trace_dbs = {}
    trace_db_done = {}
    targets = []
    other_cmds = []
    gdb = main.cc + "gdb"
    hwname = main.get_config("trace_host").name
    hookwrite_src = os.path.join(main.test_suite_dir, "hook_write.py")
    additional_cmds = ""
    if 'gdb_commands' in configs.iterkeys():
        additional_cmds = " ".join("-ex '%s'" % s for s in configs['gdb_commands'])

    gdb_cmds += ["%s %s" % (gdb, additional_cmds)]
    gdb_cmds.append("-ex 'gdb_tools plugin %s'" % hookwrite_src)
    gdb_cmds.append("-ex 'hookwrite test_instance %s'" % instance_id)
    gdb_cmds.append("-ex 'hookwrite test_trace %s'" % test_id)
    gdb_cmds.append("-ex 'hookwrite kill'")
    for s in stages:
        gdb_cmds.extend(["-ex 'hookwrite stages %s'" % s.stagename,
                        " -ex 'hookwrite until *0x%x'" % s.exitpc])

    for (s, v) in policies.iteritems():
        gdb_cmds.append("-ex 'hookwrite substages %s %s'" % (s, v))
    for s in main.enabled_stages:
        gdb_deps.extend([main.get_config("staticdb", s),
                         main.get_config("staticdb_done", s),])
                         #main.get_config("policy_db", s),
                         #main.get_config("policy_db_done", s)])
        trace_dbs[s.stagename] = os.path.join(data_root, "tracedb-%s.h5" % s.stagename)
        trace_db_done[s.stagename] = os.path.join(data_root, "tracedb-%s.completed" % s.stagename)
        gdb_targets.append(trace_dbs[s.stagename])
        done = trace_db_done[s.stagename]
        done_commands.append("touch %s" % done)
        done_targets.append(done)
        #if not hwname == "bbxmqemu":
        #    targets.append(main.get_config("openocd_log", s))
    main_cfgs["trace_db"] = lambda s: trace_dbs[s.stagename]
    main_cfgs["trace_db_done"] = lambda s: trace_db_done[s.stagename]
    return [("gdb_commands", gdb_cmds),
            ("set_config", main_cfgs), ("gdb_targets", gdb_targets),
            ("done_targets", done_targets), ('targets', targets), ('file_dep', deps),
            ("gdb_file_dep", gdb_deps), ("done_commands", done_commands)] + other_cmds


def noop(main, configs,
         stages,
         policies,
         hw_config,
         instance_id,
         test_id,
         data_root,
         quick):
    return {}


def calltrace(main, configs,
              stages,
              policies,
              hw_config,
              instance_id,
              test_id,
              data_root,
              quick):
    gdb = main.cc + "gdb"
    orgfiles = {}
    done = {}
    done_targets = []
    gdb_targets = []
    targets = []
    done_commands = []
    additional_cmds = ""
    if 'gdb_commands' in configs.iterkeys():
        additional_cmds = " ".join("-ex '%s'" % s for s in configs['gdb_commands'])
    calltrace_src = os.path.join(main.test_suite_dir, "calltrace", "calltrace.py")
    blacklist = {'spl': ['__s_init_from_arm', "get_timer", "get_timer_masked", "udelay"],
                 'main': ['__s_init_from_arm', 'get_sp', 'setup_start_tag', "get_timer", "get_timer_masked", "__udivsi3", "udelay"]}

    norec = ['sdelay']
    for s in stages:
        t = os.path.join(data_root,
                         "calltrace-%s.org" % s.stagename)
        d = os.path.join(data_root,
                         "calltrace-%s.completed" % s.stagename)
        gdb_targets.append(t)
        done_targets.append(d)
        done_commands.append("touch %s" % d)
        orgfiles[s.stagename] = t
        done[s.stagename] = d
    cmds = ["%s %s" % (gdb, additional_cmds)]
    cmds.append("-ex 'gdb_tools plugin %s'" % calltrace_src)
    stagenames = [s.stagename for s in stages]
    for (k, v) in blacklist.iteritems():
        if k not in stagenames:
            continue
        cmds.append("-ex 'calltrace blacklist %s %s'" % (k, " ".join(v)))
        cmds.append("-ex 'calltrace stage_log %s %s'" % (k, orgfiles[k]))

    cmds.append("-ex 'calltrace stages %s'" % " ".join(stagenames))
    cmds.append("-ex 'calltrace test_instance %s'" % instance_id)
    cmds.append("-ex 'calltrace test_trace %s'" % test_id)
    cmds.append("-ex 'calltrace no_recursion %s'" % " ".join(norec))
    cmds.append("-ex 'calltrace until -s main'")
    cmds.append("-ex 'calltrace kill'")
    cmds.append("-ex 'calltrace sourceinfo'")

    main_cfgs = {}
    main_cfgs["calltrace_db"] = lambda s: orgfiles[s.stagename]
    main_cfgs["calltrace_done"] = lambda s: done[s.stagename]
    return [("gdb_commands", cmds),
            ("gdb_targets", gdb_targets),
            ("set_config", main_cfgs), ("targets", targets),
            ("done_commands", done_commands),
            ("done_targets", done_targets)]


def enforce(main, configs,
            stages,
            policies,
            hw_config,
            instance_id,
            test_id,
            data_root,
            quick):
    gdb = main.cc + "gdb"
    enforce_src = os.path.join(main.test_suite_dir, "enforcement", "enforce.py")
    stagenames = [s.stagename for s in stages]
    log = os.path.join(data_root, "enforce.log")
    done = os.path.join(data_root, "enforce.completed")
    additional_cmds = ""
    if 'gdb_commands' in configs.iterkeys():
        additional_cmds = " ".join("-ex '%s'" % s for s in configs['gdb_commands'])

    cmd = ["%s %s" % (gdb, additional_cmds)]
    cmd.append("-ex 'gdb_tools plugin %s'" % enforce_src)
    for (s, v) in policies.iteritems():
        cmd.append("-ex 'enforce substages %s %s'" % (s, v))
    cmd.append("-ex 'enforce test_instance %s' " % instance_id)
    cmd.append("-ex 'enforce test_trace %s' " % test_id)
    cmd.append("-ex 'enforce log %s'" % log)
    cmd.append("-ex 'enforce until -s %s'" % stagenames[-1])
    cmd.append("-ex 'enforce stages %s'" % " ".join(stagenames))

    deps = []
    done_commands = ["touch %s" % done]
    main_cfgs = {}
    for s in [main.stage_from_name(st) for st in policies.iterkeys()]:
        deps.extend([main.get_config("staticdb", s),
                     main.get_config("staticdb_done", s),])
                     #main.get_config("policy_db", s),
                     #main.get_config("policy_db_done", s)])

    main_cfgs["enforce_log"] = log
    main_cfgs["enforce_done"] = done

    return [("gdb_commands", cmd),
            ("gdb_targets", [log]),
            ("done_targets", [done]),
            ("done_commands", done_commands),
            ("set_config", main_cfgs),
            ("gdb_file_dep", deps)]


def watchpoint(main,
               configs,
               stages,
               policies,
               hw_config,
               instance_id,
               test_id,
               data_root,
               quick):
    gdb = main.cc + "gdb"
    additional_cmds = ""
    if 'gdb_commands' in configs.iterkeys():
        additional_cmds = " ".join("-ex '%s'" % s for s in configs['gdb_commands'])
    gdb_cmds = ["%s %s -ex 'set tcp auto-retry on' -ex 'set remotetimeout -1' "
                "-ex 'set tcp connect-timeout unlimited' "
                "" % (gdb, additional_cmds)]
    if len(stages) > 1:
        return []
    deps = []
    targets = []
    done_commands = []
    s = stages[0]
    trace_db = {}
    trace_db_done = {}
    gdb_cmds.append('-ex "set pagination off"')
    gdb_cmds.append('-ex "set height unlimited"')
    gdb_cmds.append('-ex "set confirm off"')
    breakpoint = "*0x%x" % s.exitpc
    gdb_cmds.append("-ex 'break %s'" % breakpoint)
    if s.stagename == "main":
        gdb_cmds.append("-ex 'break *(0x%x) if 0'" % (s.entrypoint))
    for n in main.enabled_stages:
        trace_db[n] = os.path.join(data_root, "tracedb-%s.h5" % n)
        trace_db_done[n] = os.path.join(data_root, "tracedb-%s.completed" % n)
        done = trace_db_done[n]
        done_commands.append(("done_commands", ["touch %s" % done]))
        done_commands.append(("done_targets", [done]))
        targets.append(done)
    f = main.get_config('trace_events_file', s)
    deps.append(f)
    return done_commands + [("targets", targets),
                            ("file_dep", deps), ("gdb_commands", gdb_cmds)]


def bbxmbaremetal(main, target_config,
                  stages,
                  policies,
                  hw_config,
                  host_software_config,
                  instance_id,
                  test_id,
                  data_root,
                  is_watchpoint,
                  quick):
    return []
    openocd = os.path.join(host_software_config.root, host_software_config.binary)
    targets = []
    logs = {}
    main_cfgs = {}

    for s in main.enabled_stages:
        logs[s.stagename] = os.path.join(data_root, "openocd.log")
        main_cfgs["openocd_log"] = lambda st: logs[st.stagename]
        targets.append(logs[s.stagename])
    main_cfgs["is_bare_metal"] = True
    if len(stages) > 1:
        return []

    cmds = []
    s = stages[0]

    jtag_config = main.get_config('openocd_jtag_config_path')
    ocd_hw_config = main.get_config('openocd_hw_config_path')
    search = main.get_config('openocd_search_path')
    ocdc = [
        "gdb_port pipe", "log_output %s" % logs[s.stagename],
        "init",
        "reset init",
    ]

    c = "%s  -f %s -f %s -s %s " \
        "-c \"%s\"" % (openocd,
                       jtag_config,
                       ocd_hw_config,
                       search,
                       "; ".join(ocdc))

    cfg = {'gdb_commands': ["set tcp connect-timeout 120",
                            "set remotetimeout -1",
                            "set python print-stack full",
                            "set pagination off",
                            'set height unlimited',
                            'set confirm off',
                            "target extended-remote | %s" % c,
                            'set mem inaccessible-by-default off',
                            'mon dap apsel 0',
                            'mon init',
                            'mon reset init',
                            'mon debug_level 3',
                            'mon arm core_state arm',
                            'mon dap apsel 1',
                            'mon reg r0 0x4020dff0',
                            'mon mwb 0x4020DFF2 1',
                            'mon mwb 0x4020DFF4 6',
                            'mon dap apsel 0',
                            'mon step 0x402007FC',
                            'mon reg r0 0x4020dff0',
                            'mon mwb 0x4020DFF2 1',
                            'mon mwb 0x4020DFF4 6',
                            'mon dap apsel 1',]}
    return [("set_config", main_cfgs), ('configs', cfg)]


def framac(main,
           stages,
           configs,
           policies,
           hw_config,
           instance_id,
           test_id,
           data_root,
           quick):
    return []


def bbxmframac(main, target_config,
               stages,
               policies,
               hw_config,
               host_software_config,
               instance_id,
               test_id,
               data_root,
               is_watchpoint,
               quick):

    framac = os.path.join(host_software_config.root, host_software_config.binary)
    cmds = []
    patch_dir = os.path.join(data_root, "patches")
    callstacks = {}
    cmds.append(("command", "mkdir -p %s" % patch_dir))
    trace_dbs = {}
    trace_db_done = {}
    targets = []
    for stage in stages:
        if not stage.stagename == 'spl':
            return []
        else:
            trace_dbs[stage.stagename] = Main.get_config('trace_db', stage.stagename)
            done = trace_db_done[stage.stagename]
            trace_db_done[stage.stagename] = Main.get_config('trace_db_done', stage.stagename)
            db = trace_dbs[stage.stagename]
            callstacks[stage.stagename] = os.path.join(data_root, "callstacks.txt")
            out = os.path.join(data_root, "framac-stdout.txt")
            policy_id = policies[stage.stagename]
            args = "--stage %s -e -u -b %s -c %s -t %s -T %s -I %s -P %s " % (stage.stagename,
                                                                              patch_dir,
                                                                              callstacks[stage.stagename],
                                                                              out,
                                                                              test_id,
                                                                              instance_id,
                                                                              policy_id)
            cmd = "%s %s" % (framac, args)
            cmds.append(("interactive", cmd))

            cmds.append(("command", "touch %s" % trace_db_done[stage.stagename]))
            targets.extend([db, done])
    main_cfgs = {}
    main_cfgs["trace_db"] = lambda s: trace_dbs[s.stagename]
    main_cfgs["trace_db_done"] = lambda s: trace_db_done[s.stagename]
    main_cfgs["framac_callstacks"] = lambda s: callstacks[s.stagename]
    main_cfgs["is_bare_metal"] = False
    return [("set_config", main_cfgs), ("targets", targets)] + cmds
