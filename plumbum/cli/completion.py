import inspect
from plumbum.cli.switches import switch

def pre_quote(string):
    """Wrap \ and " to prepare for enclosing in another layer of ".." """
    return string.replace("\\", "\\\\") \
                 .replace('"', '\\"')


class Completion(object):
    def zsh_action(self, argname):
        raise NotImplemented


class FileCompletion(Completion):
    def __init__(self, glob=None):
        self.glob = glob

    def zsh_action(self, argname):
        return "_files" + (' -g "%s"' % pre_quote(self.glob) if self.glob else "")


class DirectoryCompletion(Completion):
    def zsh_action(self, argname):
        return "_path_files -/"


class ListCompletion(Completion):
    def __init__(self, *comp_list, **comp_dict):
        if len(comp_list) == 1:
            if isinstance(comp_list[0], list):
                comp_list = comp_list[0]
            elif isinstance(comp_list[0], dict):
                comp_dict = comp_list[0]
                comp_list = None

        self.comp_list = comp_list
        self.comp_dict = comp_dict

    def zsh_action(self, argname):
        if self.comp_list:
            return "(%s)" % " ".join('"%s"' % pre_quote(x)
                                     for x in self.comp_list)
        elif self.comp_dict:
            return "(%s)" % " ".join('"%s\\\\:%s"' % (pre_quote(k), pre_quote(v))
                                     for k,v in self.comp_dict.iteritems())
        else:
            return ""


class DynamicCompletion(Completion):
    def complete(self, command, prefix):
        raise NotImplemented

    def zsh_action(self, argname):
        return " __m_complete_general %s" % argname


class CallbackDynamicCompletion(DynamicCompletion):
    def __init__(self, callback, *args):
        self.callback = callback
        self.args = args

    def complete(self, command, prefix):
        return self.callback(command, prefix, *self.args)


def completion(*comp_array, **comp_dict):

    def deco(func):
        if hasattr(func, '_switch_info'):
            if comp_array:
                completion = comp_array[0]
            elif comp_dict:
                completion = next(comp_dict.itervalues())
            else:
                raise TypeError("completion() takes at least 1 argument (None given)")

            func._switch_info.completion = completion
        else:
            if func.__name__ not in ("main", "__call__"):
                raise TypeError("completion() has to be applied to the main function or switches")

            if not comp_dict:
                raise TypeError("completion() on the main function takes at least one keyword argument (None given)")
            func.__plumbum_completion__ = comp_dict

        return func

    return deco


class CompletionMixin(object):
    @switch(["--help-zsh-comp"], overridable = True, group = "Hidden-switches")
    def help_zsh_comp(self):  # @ReservedAssignment
        """Generates zsh completion syntax and quits"""

        def switches(command):
            by_groups = {}
            for func, si in command._switches_by_func.iteritems():
                if si.group == 'Hidden-switches':
                    continue
                by_groups.setdefault(si.group, []).append(si)

            def readd_dashes_and_join(flags, sep=","):
                return sep.join(("-" if len(n) == 1 else "--") + n for n in flags)

            for grp, swinfos in sorted(by_groups.items(), key = lambda item: item[0]):
                for si in sorted(swinfos, key = lambda si: si.names):
                    swnames = readd_dashes_and_join(si.names)
                    if len(si.names) > 1:
                        swnames = '{' + swnames + '}'

                    if si.argtype:
                        if isinstance(si.completion, Completion):
                            # use + as a marker for switches
                            name = '+' + si.names[0]
                            zsh_action = si.completion.zsh_action(name)
                            argtype = ": :%s" % pre_quote(zsh_action)
                        else:
                            argtype = ": : "
                    else:
                        argtype = ""

                    if si.list:
                        list = "\\*"
                    else:
                        list = ""

                    if si.excludes:
                        excludes = "'(%s)'" % readd_dashes_and_join(si.excludes, " ")
                    else:
                        excludes = ""

                    if si.help:
                        help = pre_quote(si.help)
                    else:
                        help = ""

                    if si.mandatory:
                        help += " (mandatory)"

                    yield '%s%s%s"[%s]%s"' % (excludes,
                                              list,
                                              swnames,
                                              help,
                                              argtype)

        def arguments(command):
            specs = []

            m_args, m_varargs, _, m_defaults = inspect.getargspec(command.main)
            comp_dict = getattr(command.main, "__plumbum_completion__", dict())
            no_of_mandatory_args = len(m_args[1:])
            if m_defaults:
                no_of_mandatory_args -= len(m_defaults)
                if command._subcommands:

                    sys.stderr.write("Mixing subcommands and optional "
                                     "arguments is not fully supported, "
                                     "expect unexpected behaviour.\n")
            class NoCompletion(Completion):
                def zsh_action(arg): return ' '
            for n, arg in enumerate(m_args[1:]):
                optional = n >= no_of_mandatory_args
                zsh_action = comp_dict.get(arg, NoCompletion()).zsh_action()
                specs.append("':%s%s:%s'"
                             % (':' if optional else '', arg, zsh_action))

            if m_varargs:
                if command._subcommands:
                    sys.stderr.write("Mixing subcommands and variable "
                                     "arguments is not supported.\n"
                                     "Ignoring the argument %s.\n" % m_varargs)
                else:
                    zsh_action = comp_dict.get(m_varargs, NoCompletion()) \
                                              .zsh_action(m_varargs)
                    specs.append("'*:::%s:%s'" % (m_varargs,
                                                  zsh_action))

            return specs

        def subcommands(command, prefix):
            commands = command._subcommands
            if not commands:
                return "", [], ""

            def first_line(string):
                return string[:string.find("\n")]

            func_defs = []
            func_descriptions = []
            for name, subcls in sorted(commands.items(), key=lambda it: it[0]):
                subapp = subcls.get()

                desc = first_line(subapp.DESCRIPTION
                                  if subapp.DESCRIPTION
                                  else inspect.getdoc(subapp))

                subapp_instance = subapp(self.executable)
                subapp_instance.parent = command

                func_defs += zsh_completion_functions("%s_%s" % (prefix, name),
                                                      subapp_instance)
                func_descriptions.append('"%s\\:%s"' % (name, pre_quote(desc)))

            func_specs = ("': :((" + " ".join(func_descriptions) + "))'",
                          "'*:: : _next %s'" % prefix)

            func_extras = "__m_subcommands=(%s)\n" % " ".join(commands)
            return func_specs, func_defs, func_extras

        def zsh_completion_functions(name, command):
            args_specs = arguments(command)
            func_specs, func_defs, func_extras = subcommands(command, name)
            switch_specs = switches(command)

            func_defs.append("%s() {\n" % name +
                             "_debug %s\n" % name +
                             ("typeset __m_words __m_current=$CURRENT __m_subcommands\n"
                              "__m_words=(\"${(@)words}\")\n"
                              if command.parent is None else "") +
                             func_extras +
                             "_arguments -s -A ':' " +
                             " ".join(switch_specs) + " " +
                             " ".join(args_specs) + " " +
                             " ".join(func_specs) +
                             "\n}\n")

            return func_defs

        func_defs = zsh_completion_functions("_" + self.PROGNAME, self)

        func_defs.append("""
_debug() {
  echo "=== $1 ===" >> /tmp/log
  echo "expl: $expl" >> /tmp/log
  echo "CURRENT: $CURRENT" >> /tmp/log
  echo "words: $words" >> /tmp/log
  echo "line: $line" >> /tmp/log
  echo "context: $curcontext" >> /tmp/log
}
        """)

        func_defs.append("""
__is_word_in_array () {
  local word=$1; shift
  [[ ${@[(i)$word]} -le ${#@} ]] || return 1
}

_next() {
  local p n f
  p=$1; shift
  for n in {1..$(( $CURRENT-1 ))}
  if __is_word_in_array ${words[$n]} ${__m_subcommands}
  then
    f=${p}_$words[$n]
    compset -n $n
    $f
    break
  fi
}
        """)

        func_defs.append("""
__m_remove_subcommand () {
  for n in {$__m_current..${#__m_words}}
  if __is_word_in_array ${__m_words[$n]} ${__m_subcommands}
  then
    __m_words=("${(@)__m_words[1,$(( $n - 1 ))]}")
    break
  fi
}

__m_complete_general () {
  local results global_expl="$expl" expl where
  where=$1; shift
  _debug "complete_general with path $where"

  __m_remove_subcommand
  results=($(_call_program complete-general \\"${(@)__m_words}\\" --complete $where:$CURRENT 2>> /tmp/log))
  _wanted complete-general expl '' compadd $global_expl - $results
}

__m_complete_path_like () {
  local results global_expl="$expl" expl where
  where=$1; shift
  _debug "complete_path_like with path $where"

  __m_remove_subcommand
  results=($(_call_program complete-path-like \\"${(@)__m_words}\\" --complete $where:$CURRENT 2>> /tmp/log))
  _wanted complete-path-like expl '' _multi_parts $global_expl -f - / results
}
        """)

        print ("#compdef %s\n\n" % self.PROGNAME + "\n\n" \
               + "\n".join(func_defs) + "\n" + '_%s "$@"' % self.PROGNAME)

    @switch(["--complete"], argtype=str, overridable = True, group = "Hidden-switches")
    def complete(self, swfuncs, tailargs):  # @ReservedAssignment
        """Hidden switch for dynamic completion"""

        complete_func = self._switches_by_name['complete'].func
        for _, f, sf in sorted([(sf.index, f, sf)
                                for f, sf in swfuncs.iteritems()]):
            if f == complete_func:
                argname, current = sf.val[0].split(':')
            else:
                f(self, *sf.val)

        if argname.startswith('+'):
            swinfo = self._switches_by_name[argname[1:]]
            func = swinfo.func
            prefix = swfuncs[func].val[0]
            completion = swinfo.completion
        else:
            comp_dict = getattr(self.main, "__plumbum_completion__", dict())
            try:
                completion = comp_dict[argname]
            except KeyError:
                return

            m_args, m_varargs, _, _ = inspect.getargspec(self.main)
            m_args = m_args[1:] # remove self

            try:
                index = m_args.index(argname)
                prefix = tailargs[index]
            except ValueError:
                # must be in m_varargs then
                assert(m_varargs == argname)
                prefix = tailargs[len(m_args) + int(current) - 1]

        for x in completion.complete(self, prefix):
            print x
