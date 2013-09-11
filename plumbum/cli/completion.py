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
            if not comp_dict:
                raise TypeError("completion() on the main function takes at least one keyword argument (None given)")
            if func.__name__ not in ("main", "__call__"):
                raise TypeError("completion() has to be applied to the main function or switches")

            func.__plumbum_completion__ = comp_dict

        return func

    return deco
