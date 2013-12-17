import inspect
import sys
from plumbum.cli.switches import switch


def pre_quote(string):
    """Wrap \ and " to prepare for enclosing in another layer of ".." """
    return string.replace("\\", "\\\\") \
                 .replace('"', '\\"')


## Completion objects
#

class Completion(object):
    '''Abstract base class for Completion objects.

Completion objects are used by the completion decorator or the
completion argument for attribute constructors (SwitchAttr, ...).

They must define a zsh_action function, which provides zsh specific
code, describing a set of completion possibilities. It is called by
the ``--help-zsh-comp``-switch-function to generate the zsh completion
file. (Refer to the zshcompsys manpage for further details on action).
'''

    def zsh_action(self, argname):
        raise NotImplemented


class FileCompletion(Completion):
    '''Completion class for completing filenames

Arguments:
glob -- a glob pattern to filter shown filenames (default None)
    , possibly using a pattern.
'''

    def __init__(self, glob=None):
        self.glob = glob

    def zsh_action(self, argname):
        return "_files" + (' -g "%s"' % pre_quote(self.glob) if self.glob else "")


class DirectoryCompletion(Completion):
    '''Completion class for completing directory names'''
    def zsh_action(self, argname):
        return "_path_files -/"


class ListCompletion(Completion):
    '''Completion class for completing a static list (possibly with comments)

Keywords:
*comp_list  -- list of completion possibilities without comments
**comp_dict -- completion possibilities as dictionary
               keys are the completion strings,
               values are the respective comments

It's not possible to mix the two approaches.

Usage examples:
ListCompletion("foo", "bar")
ListCompletion(foo="Help for foo", bar="Help for bar")

Alternative usage:
ListCompletion(("foo", "bar"))
ListCompletion({ "foo": "Help for foo", "bar": "Help for bar"})
'''
    def __init__(self, *comp_list, **comp_dict):
        # Handle the alternative usage case
        if len(comp_list) == 1:
            if isinstance(comp_list[0], list):
                # a sole list of completions was passed in
                comp_list = comp_list[0]
            elif isinstance(comp_list[0], dict):
                # a sole dictionary was passed in
                comp_dict = comp_list[0]
                comp_list = None

        self.comp_list = comp_list
        self.comp_dict = comp_dict

    def zsh_action(self, argname):
        if self.comp_list:
            # syntax looks like: ("foo" "bar")
            return "(%s)" % " ".join('"%s"' % pre_quote(x)
                                     for x in self.comp_list)
        elif self.comp_dict:
            # syntax looks like:
            # ("foo\\:Help for foo" "bar\\:Help for bar")
            return "(%s)" % " ".join('"%s\\\\:%s"' % (pre_quote(k), pre_quote(v))
                                     for k,v in self.comp_dict.iteritems())
        else:
            return ""


class DynamicCompletion(Completion):
    '''Abstract base class for DynamicCompletion objects.

They must define a zsh_action function like Completion, which provides
zsh specific code, describing a set of completion possibilities. It is
called by the ``--help-zsh-comp``-switch-function to generate the zsh
completion file. (Refer to the zshcompsys manpage for further details
on action).

Additionally they need to define a complete function. It is called,
when completing its associated argument and asked to return a list of
possible further completions.

Also refer to the ``complete`` switch method in CompletionMixin.
    '''

    def complete(self, command, prefix, posargs):
        '''Return the possible completions

Arguments:
command -- instance of the current subcommand
           (with all switches and arguments already initialised)
prefix  -- text already supplied for the current argument
posargs -- dictionary mapping the positional arguments to their values

Its two arguments are the  () and the prefix from which to complete.
        '''
        raise NotImplemented

    def zsh_action(self, argname):
        # zsh_action is usually one of __m_complete_(general|pathlike)
        return " __m_complete_general %s" % argname


class CallbackDynamicCompletion(DynamicCompletion):
    '''Wrapper to use a callback function for dynamic completions

Simplifies using DynamicCompletions by not having to subclass
DynamicCompletion directly.
    '''
    def __init__(self, callback, *args):
        '''Constructor.

Arguments:
callback -- callback method, with a signature like
            cb(command, prefix, posargs, *args) returning completionlist
*args    -- Additional arguments to be passed to the callback method
        '''
        self.callback = callback
        self.args = args

    def complete(self, command, prefix, posargs):
        '''Return completion possibilities.

Arguments:
command -- current subcommand or Application
prefix  -- text already supplied for the argument
posargs -- dictionary mapping the positional arguments to their values
        '''
        return self.callback(command, prefix, posargs, *self.args)


#
# decorator
#
def completion(*comp_array, **comp_dict):
    '''Decorator to mark arguments supporting Completions.

It can be applied to main function of Subcommand or Application
and SwitchMethods of any type.

Usage example:

class Command(plumbum.cli.Application)
  @plumbum.cli.completion(tpv.cli.ListCompletion("foo", "bar"))
  @switch(["--arg"])
  def arg(self):
    [...]

  @plumbum.cli.completion(directory=tpv.cli.CallbackDynamicCompletion(cb),
                          filenames=tpv.cli.FileCompletion(glob="*.py"))
  def main(self, directory, *filenames):
    [...]
    '''

    def deco(func):
        '''Installs the completion objects into the given method ``func``'''

        if hasattr(func, '_switch_info'):
            # func describes a switch

            # the first argument supplied via positional arguments or
            # keyword arguments is taken as the completion object
            if comp_array:
                completion = comp_array[0]
            elif comp_dict:
                completion = next(comp_dict.itervalues())
            else:
                raise TypeError("completion() takes at least 1 argument (None given)")

            # in a switch we store the completion object within its
            # _switchinfo instance, already set in place by the switch
            # decorator.
            func._switch_info.completion = completion
        else:
            # func is the main function of a Subcommand/Application
            if func.__name__ not in ("main", "__call__"):
                raise TypeError("completion() has to be applied to the main function or switches")

            # completion objects must be given as keyword arguments to
            # be able to identify the arguments to be completed
            if not comp_dict:
                raise TypeError("completion() on the main function takes at least one keyword argument (None given)")

            # this dictionary of argument keyword to completion object
            # is stored in the __plumbum_completion__ attribute of the
            # function
            func.__plumbum_completion__ = comp_dict

        return func

    return deco


class CompletionMixin(object):
    '''Mixin class to cli.Application, which provides switches for zsh completion

Usage example:

class MyApp(cli.Application, cli.CompletionMixin):
    @cli.completion(arg=ListCompletion("foo", "bar"))
    def main(self, arg):
       [...]

provides the top-level switches --help-zsh-comp, which generates zsh
completion definitions, and an internal switch --complete to support
dynamic completion.
    '''
    @switch(["--help-zsh-comp"], overridable = True, group = "Hidden-switches")
    def help_zsh_comp(self):  # @ReservedAssignment
        '''Generates zsh completion syntax to stdout and quits

It iterates over all switches and arguments to the main function of
the Application and then recursively over all Subcommands and creates
their static zsh completion code/definitions.

Usage:
myapp --help-zsh-comp > <path_to_a_directory_from_fpath>/_myapp
        '''

        def switches(command):
            '''Return the zsh _argument specifications for the switches of ``command`` '''

            # Group the plumbum switches by their group parameter and
            # filter out switches in the special group Hidden-switches
            # (--complete is part of that group)
            by_groups = {}
            for func, si in command._switches_by_func.iteritems():
                if si.group == 'Hidden-switches':
                    continue
                by_groups.setdefault(si.group, []).append(si)

            # plumbum removes the dashes in the names of switches, we
            # need them for _arguments
            def readd_dashes_and_join(flags, sep=","):
                return sep.join(("-" if len(n) == 1 else "--") + n for n in flags)

            # iterate over groups, then switches in alphabetical order
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

                    # an argument spec looks like:
                    # "(<excludes>)<switchname>[<help text>]: :<zsh_action>"
                    yield '%s%s%s"[%s]%s"' % (excludes,
                                              list,
                                              swnames,
                                              help,
                                              argtype)

        def arguments(command):
            '''Return argument specifications for the application or subcommand ``command``'''
            specs = []

            # the existing arguments are given by the function
            # specification of the command's main function, as
            # returned by inspect.

            # From the documentation for inspect.getargspec:
            # m_args is a list of the argument names. m_varargs is the
            # name of the * argument or None. m_defaults is a tuple of
            # default argument values or None if there are no default
            # arguments; if this tuple has n elements, they correspond
            # to the last n elements listed in args.
            m_args, m_varargs, _, m_defaults = inspect.getargspec(command.main)

            # completion objects for arguments have been stored in the
            # __plumbum_completion__ attribute by the completion decorator
            comp_dict = getattr(command.main, "__plumbum_completion__", dict())

            # the number of the mandatory arguments are the positional
            # arguments from m_args (without self) minus those with
            # default values
            no_of_mandatory_args = len(m_args[1:])
            if m_defaults:
                no_of_mandatory_args -= len(m_defaults)
                if command._subcommands:
                    # supporting them is difficult, because then the
                    # _arguments function has to decide, whether a
                    # given argument is still a positional argument or
                    # already a subcommand. doesn't work, with our
                    # completion methods, yet!
                    sys.stderr.write("Mixing subcommands and optional "
                                     "arguments is not fully supported, "
                                     "expect unexpected behaviour.\n")

            # the zsh action corresponding to No Completion is ' '
            class NoCompletion(Completion):
                def zsh_action(self, argname): return ' '

            # zsh argument specs for positional arguments, like
            # :${argname}:${zsh_action}
            # or for optional arguments, like
            # ::${argname}:${zsh_action}
            for n, arg in enumerate(m_args[1:]):
                optional = n >= no_of_mandatory_args
                zsh_action = comp_dict.get(arg, NoCompletion()).zsh_action(arg)
                specs.append("':%s%s:%s'"
                             % (':' if optional else '', arg, zsh_action))

            # argument specs for a * argument, works with three colons
            # can't be mixed with subcommands either.
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
            '''Return all specifications for the subcommands of ``command`` and their children

Arguments:
command -- instance of Application or Subcommand
prefix  -- name of the completion function to the current ``command``,
           which is used as prefix for the zsh completion functions of the
           subcommands.

Returns a tuple (func_specs, func_defs, func_extras), where:
func_specs  -- the parameters to the _arguments function for ``command``
func_defs   -- the list of completion functions for all subcommands recursively
func_extras -- shell commands executed before the _arguments call,
               used to set __m_subcommands variable, necessary for subcommand
               resolution.
'''
            # _subcommands is a dictionary like
            # { <name> : Subcommand(<name>, <class>) }
            commands = command._subcommands
            if not commands:
                # empty func_specs, no func_defs and empty func_extras
                return "", [], ""

            def first_line(string):
                return string[:string.find("\n")]

            func_defs = []
            func_descriptions = []
            for name, subcls in sorted(commands.items(), key=lambda it: it[0]):
                # the class of the subcommand
                subapp = subcls.get()

                desc = first_line(subapp.DESCRIPTION
                                  if subapp.DESCRIPTION
                                  else inspect.getdoc(subapp))

                # instantiate
                subapp_instance = subapp(self.executable)
                subapp_instance.parent = command

                # collect the zsh functions for the subcommand's branch
                func_defs += zsh_completion_functions("%s_%s" % (prefix, name),
                                                      subapp_instance)
                func_descriptions.append('"%s\\:%s"' % (name, pre_quote(desc)))

            func_specs = ('": :((' + pre_quote(" ".join(func_descriptions)) + '))"',
                          "'*:: : _next %s'" % prefix)
            # func_specs have the form
            #     ': :(("<name>\:<desc>" "<name2>\:<desc2>" ...))
            #     '*:: : _next <prefix>'

            func_extras = "__m_subcommands=(%s)\n" % " ".join(commands)
            return func_specs, func_defs, func_extras

        def zsh_completion_functions(name, command):
            '''Returns a list of zsh completion code-functions for the application
or subcommand ``command``.

Collects the definitions provided by the functions ``switches``,
``arguments`` and ``subcommands``. As ``subcommands`` recursively
calls back into ``zsh_completion_functions``, the whole definition
tree of an application is generated.

Arguments:
name    -- string, used as function name in the zsh completion file and has the
           form "_${shellname}[_${subcommand1}[_${subcommand2}[...]]]",
           i.e. _xin_generation_remove
command -- instance of plumbum.cli.Application, representing the current
           application or subcommand
            '''
            args_specs = arguments(command)
            func_specs, func_defs, func_extras = subcommands(command, name)
            switch_specs = switches(command)

            func_defs.append("%s() {\n" % name +
                             "_debug %s\n" % name +
                             ("typeset __m_words __m_current=$CURRENT __m_subcommands\n"
                              "__m_words=(\"${(@)words}\")\n"
                              if command.parent is None else "") +
                             func_extras +
                             "_arguments -s " +
                             ("-A '-*' " if not command._subcommands else "") +
                             "':' " +
                             " ".join(switch_specs) + " " +
                             " ".join(args_specs) + " " +
                             " ".join(func_specs) +
                             "\n}\n")

            # the resulting list of functions looks like:
            #
            # _xin() {
            #   _debug _xin
            #   typeset __m_words __m_current=$CURRENT __m_subcommands
            #   __m_words=("${(@)words}")
            #   __m_subcommands=(profile search)
            #   _arguments -s -A ':' \
            #     {-h,--help}"[Prints this help message and quits]" \
            #     --version"[Prints the program's version and quits]" \
            #     ': :(("profile\:Manage nix profiles" \
            #           "search\:Search packages"))' \
            #     '*:: : _next _xin'
            # }
            #
            # function for subcommand search (the one for profile is omitted):
            #
            # _xin_search() {
            #   _debug _xin_search
            #   _arguments -s -A ':' \
            #     {-h,--help}"[Prints this help message and quits]" \
            #     --version"[Prints the program's version and quits]" \
            #     {-i,--installed}"[Search packages installed in your profile]"\
            #     {-p,--profile}"[Search packages installed in profile..]: : "\
            #     '::querystr: '
            # }
            #
            # arguments to the _arguments function are provided by the
            # 3 functions for switches, arguments and subcommands and
            # are saved in *_specs variables.
            #
            #     {-h,--help}"[Prints this help message and quits]" \
            #     --version"[Prints the program's version and quits]" \
            # is an example of switch_specs.
            #
            #     '::querystr: '
            # is an example for args_specs.
            #
            #     ': :(("generation\:Manage..."...))
            #     '*:: : _next _xin'
            # is from the func_specs, making sure the next level of
            # subcommand functions is invoked. for the call to _next
            # to work reliably, func_extras provides a variable like
            #   __m_subcommands=(profile search)

            return func_defs

        func_defs = zsh_completion_functions("_" + self.PROGNAME, self)

        ## A set of helper methods, which might be better fitting into
        ## an external template file.

        # A zsh method for debugging purposes, TODO should be conditional
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

        # Helper methods, which make sure the next subcommand
        # definition is found
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

        # Helper methods, necessary for dynamic completion
        # TODO error piping to /tmp/log should at least be conditional
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
  [ "${line:0:1}" = "-" ] && return
  _debug "complete_general with path $where"

  __m_remove_subcommand
  results=($(_call_program complete-general \\"${(@)__m_words}\\" --complete $where:$CURRENT 2>> /tmp/log))
  _wanted complete-general expl '' compadd $global_expl - $results
}

__m_complete_path_like () {
  local results global_expl="$expl" expl where
  where=$1; shift
  [ "${line:0:1}" = "-" ] && return
  _debug "complete_path_like with path $where"

  __m_remove_subcommand
  results=($(_call_program complete-path-like \\"${(@)__m_words}\\" --complete $where:$CURRENT 2>> /tmp/log))
  _wanted complete-path-like expl '' _multi_parts $global_expl -f - / results
}
        """)

        # Print all functions to stdout, together with the usual zsh
        # completion header and footer
        print ("#compdef %s\n\n" % self.PROGNAME + "\n\n" \
               + "\n".join(func_defs) + "\n" + '_%s "$@"' % self.PROGNAME)


    @switch(["--complete"], argtype=str, overridable = True, group = "Hidden-switches")
    def complete(self, swfuncs, tailargs):  # @ReservedAssignment
        """Hidden switch for dynamic completion

Example, given that a subcommand profile is defined like

    class Profile(Application):
        @plumbum.cli.completion(profilenames=CallbackDynamicCompletion(cb))
        int main(self, *profilenames):
            pass

Then, when the user tries to complete at TAB after entering part of a
profile name,

    xin profile --someswitch prefixTAB

Zsh calls effectively

    -> xin profile --someswitch prefix --complete "profilenames:1"

where the argument to the complete switch is <argname>:<current_position>.

The self argument of the complete function always refers to the most
specific Application or subcommand; i.e. it refers to the Profile
subcommand.
        """

        # build a dictionary posargs from the positional arguments of
        # tailargs. it will be passed to the completion object
        m_args, m_varargs, _, _ = inspect.getargspec(self.main)
        m_args = m_args[1:]  # remove self

        posargs = dict(zip(m_args, tailargs))
        if m_varargs is not None and len(m_args) < len(tailargs):
            posargs[m_varargs] = tailargs[len(m_args):]

        # as the switch --complete is intercepted at the beginning of
        # Application._validate_args, the methods corresponding to
        # switches of this command have to be called by us (normally
        # this is done in Application.run just before instantiating
        # the current subcommand).
        # The attributes they provide may be used by the complete
        # function of a DynamicCompletion object.
        # For more information check Application.run and
        # Application._validate_args.
        complete_func = self._switches_by_name['complete'].func
        for _, f, sf in sorted([(sf.index, f, sf)
                                for f, sf in swfuncs.iteritems()]):
            # iterate over switches
            if f == complete_func:
                # don't call the complete switch (us), instead extract
                # argname and current position from its argument.
                argname, current = sf.val[0].split(':')
            else:
                f(self, *sf.val)

        # argname is either the field name of an argument of the
        # subcommand's main function or the name of a switch. for the
        # the latter it is prefixed by a + sign.
        if argname.startswith('+'):
            # switch

            # get the completion object and the prefix from
            # the SwitchInfo object of the switch
            swinfo = self._switches_by_name[argname[1:]]
            func = swinfo.func
            prefix = swfuncs[func].val[0]
            completion = swinfo.completion

            if swinfo.list:
                # heuristically just assume we are completing the last
                # switch, there is no way currently to make a more
                # informed choice
                prefix = prefix[-1]
        else:
            # argument of main method

            # the completion objects are saved in the dictionary on
            # the __plumbum__completion__ attribute of the main method
            comp_dict = getattr(self.main, "__plumbum_completion__", dict())
            try:
                completion = comp_dict[argname]

                prefix = posargs[argname]
                if argname == m_varargs:
                    # current starts counting at 1
                    prefix = prefix[int(current) - 1]
            except KeyError:
                # should only happen, when an inquisitive user tries
                # to handcraft --complete
                return

        # print the completions the completion object returns
        for x in completion.complete(self, prefix, posargs):
            print x
