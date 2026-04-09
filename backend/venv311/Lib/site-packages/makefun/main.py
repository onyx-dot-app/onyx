# Authors: Sylvain MARIE <sylvain.marie@se.com>
#          + All contributors to <https://github.com/smarie/python-makefun>
#
# License: 3-clause BSD, <https://github.com/smarie/python-makefun/blob/master/LICENSE>
from __future__ import print_function

import functools
import re
import sys
import itertools
from collections import OrderedDict
from copy import copy
from inspect import getsource
from keyword import iskeyword
from textwrap import dedent
from types import FunctionType


if sys.version_info >= (3, 0):
    is_identifier = str.isidentifier
else:
    def is_identifier(string):
        """
        Replacement for `str.isidentifier` when it is not available (e.g. on Python 2).
        :param string:
        :return:
        """
        if len(string) == 0 or string[0].isdigit():
            return False
        return all([(len(s) == 0) or s.isalnum() for s in string.split("_")])

try:  # python 3.3+
    from inspect import signature, Signature, Parameter
except ImportError:
    from funcsigs import signature, Signature, Parameter

try:
    from inspect import iscoroutinefunction
except ImportError:
    # let's assume there are no coroutine functions in old Python
    def iscoroutinefunction(f):
        return False

try:
    from inspect import isgeneratorfunction
except ImportError:
    # assume no generator function in old Python versions
    def isgeneratorfunction(f):
        return False

try:
    from inspect import isasyncgenfunction
except ImportError:
    # assume no generator function in old Python versions
    def isasyncgenfunction(f):
        return False

try:  # python 3.5+
    from typing import Callable, Any, Union, Iterable, Dict, Tuple, Mapping
except ImportError:
    pass


PY2 = sys.version_info < (3,)
if not PY2:
    string_types = str,
else:
    string_types = basestring,  # noqa


# macroscopic signature strings checker (we do not look inside params, `signature` will do it for us)
FUNC_DEF = re.compile(
    '(?s)^\\s*(?P<funcname>[_\\w][_\\w\\d]*)?\\s*'
    '\\(\\s*(?P<params>.*?)\\s*\\)\\s*'
    '(((?P<typed_return_hint>->\\s*[^:]+)?(?P<colon>:)?\\s*)|:\\s*#\\s*(?P<comment_return_hint>.+))*$'
)


def create_wrapper(wrapped,
                   wrapper,
                   new_sig=None,               # type: Union[str, Signature]
                   prepend_args=None,          # type: Union[str, Parameter, Iterable[Union[str, Parameter]]]
                   append_args=None,           # type: Union[str, Parameter, Iterable[Union[str, Parameter]]]
                   remove_args=None,           # type: Union[str, Iterable[str]]
                   func_name=None,             # type: str
                   inject_as_first_arg=False,  # type: bool
                   add_source=True,            # type: bool
                   add_impl=True,              # type: bool
                   doc=None,                   # type: str
                   qualname=None,              # type: str
                   co_name=None,               # type: str
                   module_name=None,           # type: str
                   **attrs
                   ):
    """
    Creates a signature-preserving wrapper function.
    `create_wrapper(wrapped, wrapper, **kwargs)` is equivalent to `wraps(wrapped, **kwargs)(wrapper)`.

    See `@makefun.wraps`
    """
    return wraps(wrapped, new_sig=new_sig, prepend_args=prepend_args, append_args=append_args, remove_args=remove_args,
                 func_name=func_name, inject_as_first_arg=inject_as_first_arg, add_source=add_source,
                 add_impl=add_impl, doc=doc, qualname=qualname, module_name=module_name, co_name=co_name,
                 **attrs)(wrapper)


def getattr_partial_aware(obj, att_name, *att_default):
    """ Same as getattr but recurses in obj.func if obj is a partial """

    val = getattr(obj, att_name, *att_default)
    if isinstance(obj, functools.partial) and \
            (val is None or att_name == '__dict__' and len(val) == 0):
        return getattr_partial_aware(obj.func, att_name, *att_default)
    else:
        return val


def create_function(func_signature,             # type: Union[str, Signature]
                    func_impl,                  # type: Callable[[Any], Any]
                    func_name=None,             # type: str
                    inject_as_first_arg=False,  # type: bool
                    add_source=True,            # type: bool
                    add_impl=True,              # type: bool
                    doc=None,                   # type: str
                    qualname=None,              # type: str
                    co_name=None,               # type: str
                    module_name=None,           # type: str
                    **attrs):
    """
    Creates a function with signature `func_signature` that will call `func_impl` when called. All arguments received
    by the generated function will be propagated as keyword-arguments to `func_impl` when it is possible (so all the
    time, except for var-positional or positional-only arguments that get passed as *args. Note that positional-only
    does not yet exist in python but this case is already covered because it is supported by `Signature` objects).

    `func_signature` can be provided in different formats:

     - as a string containing the name and signature without 'def' keyword, such as `'foo(a, b: int, *args, **kwargs)'`.
       In which case the name in the string will be used for the `__name__` and `__qualname__` of the created function
       by default
     - as a `Signature` object, for example created using `signature(f)` or handcrafted. Since a `Signature` object
       does not contain any name, in this case the `__name__` and `__qualname__` of the created function will be copied
       from `func_impl` by default.

    All the other metadata of the created function are defined as follows:

     - default `__name__` attribute (see above) can be overridden by providing a non-None `func_name`
     - default `__qualname__` attribute (see above) can be overridden by providing a non-None `qualname`
     - `__annotations__` attribute is created to match the annotations in the signature.
     - `__doc__` attribute is copied from `func_impl.__doc__` except if overridden using `doc`
     - `__module__` attribute is copied from `func_impl.__module__` except if overridden using `module_name`
     - `__code__.co_name` (see above) defaults to the same value as the above `__name__` attribute, except when that
       value is not a valid Python identifier, in which case it will be `<lambda>`. It can be  overridden by providing
       a `co_name` that is either a valid Python identifier or `<lambda>`.

    Finally two new attributes are optionally created

     - `__source__` attribute: set if `add_source` is `True` (default), this attribute contains the source code of the
     generated function
     - `__func_impl__` attribute: set if `add_impl` is `True` (default), this attribute contains a pointer to
     `func_impl`

    A lambda function will be created in the following cases:

     - when `func_signature` is a `Signature` object and `func_impl` is itself a lambda function,
     - when the function name, either derived from a `func_signature` string, or given explicitly with `func_name`,
       is not a valid Python identifier, or
     - when the provided `co_name` is `<lambda>`.

    :param func_signature: either a string without 'def' such as "foo(a, b: int, *args, **kwargs)" or "(a, b: int)",
        or a `Signature` object, for example from the output of `inspect.signature` or from the `funcsigs.signature`
        backport. Note that these objects can be created manually too. If the signature is provided as a string and
        contains a non-empty name, this name will be used instead of the one of the decorated function.
    :param func_impl: the function that will be called when the generated function is executed. Its signature should
        be compliant with (=more generic than) `func_signature`
    :param inject_as_first_arg: if `True`, the created function will be injected as the first positional argument of
        `func_impl`. This can be handy in case the implementation is shared between several facades and needs
        to know from which context it was called. Default=`False`
    :param func_name: provide a non-`None` value to override the created function `__name__` and `__qualname__`. If this
        is `None` (default), the `__name__` will default to the one of `func_impl` if `func_signature` is a `Signature`,
        or to the name defined in `func_signature` if `func_signature` is a `str` and contains a non-empty name.
    :param add_source: a boolean indicating if a '__source__' annotation should be added to the generated function
        (default: True)
    :param add_impl: a boolean indicating if a '__func_impl__' annotation should be added to the generated function
        (default: True)
    :param doc: a string representing the docstring that will be used to set the __doc__ attribute on the generated
        function. If None (default), the doc of func_impl will be used.
    :param qualname: a string representing the qualified name to be used. If None (default), the `__qualname__` will
        default to the one of `func_impl` if `func_signature` is a `Signature`, or to the name defined in
        `func_signature` if `func_signature` is a `str` and contains a non-empty name.
    :param co_name: a string representing the name to be used in the compiled code of the function. If None (default),
        the `__code__.co_name` will default to the one of `func_impl` if `func_signature` is a `Signature`, or to the
        name defined in `func_signature` if `func_signature` is a `str` and contains a non-empty name.
    :param module_name: the name of the module to be set on the function (under __module__ ). If None (default),
        `func_impl.__module__` will be used.
    :param attrs: other keyword attributes that should be set on the function. Note that `func_impl.__dict__` is not
        automatically copied.
    :return:
    """
    # grab context from the caller frame
    try:
        attrs.pop('_with_sig_')
        # called from `@with_signature`
        frame = _get_callerframe(offset=1)
    except KeyError:
        frame = _get_callerframe()
    evaldict, _ = extract_module_and_evaldict(frame)

    # name defaults
    user_provided_name = True
    if func_name is None:
        # allow None, this will result in a lambda function being created
        func_name = getattr_partial_aware(func_impl, '__name__', None)
        user_provided_name = False

    # co_name default
    user_provided_co_name = co_name is not None
    if not user_provided_co_name:
        if func_name is None:
            co_name = '<lambda>'
        else:
            co_name = func_name
    else:
        if not (_is_valid_func_def_name(co_name)
                or _is_lambda_func_name(co_name)):
            raise ValueError("Invalid co_name %r for created function. "
                             "It is not possible to declare a function "
                             "with the provided co_name." % co_name)

    # qname default
    user_provided_qname = True
    if qualname is None:
        qualname = getattr_partial_aware(func_impl, '__qualname__', None)
        user_provided_qname = False

    # doc default
    if doc is None:
        doc = getattr(func_impl, '__doc__', None)
        # note: as opposed to what we do in `@wraps`, we cannot easily generate a better doc for partials here.
        # Indeed the new signature may not easily match the one in the partial.

    # module name default
    if module_name is None:
        module_name = getattr_partial_aware(func_impl, '__module__', None)

    # input signature handling
    if isinstance(func_signature, str):
        # transform the string into a Signature and make sure the string contains ":"
        func_name_from_str, func_signature, func_signature_str = get_signature_from_string(func_signature, evaldict)

        # if not explicitly overridden using `func_name`, the name in the string takes over
        if func_name_from_str is not None:
            if not user_provided_name:
                func_name = func_name_from_str
            if not user_provided_qname:
                qualname = func_name
            if not user_provided_co_name:
                co_name = func_name

        create_lambda = not _is_valid_func_def_name(co_name)

        # if lambda, strip the name, parentheses and colon from the signature
        if create_lambda:
            name_len = len(func_name_from_str) if func_name_from_str else 0
            func_signature_str = func_signature_str[name_len + 1: -2]
        # fix the signature if needed
        elif func_name_from_str is None:
            func_signature_str = co_name + func_signature_str

    elif isinstance(func_signature, Signature):
        # create the signature string
        create_lambda = not _is_valid_func_def_name(co_name)

        if create_lambda:
            # create signature string (or argument string in the case of a lambda function
            func_signature_str = get_lambda_argument_string(func_signature, evaldict)
        else:
            func_signature_str = get_signature_string(co_name, func_signature, evaldict)
    else:
        raise TypeError("Invalid type for `func_signature`: %s" % type(func_signature))

    # extract all information needed from the `Signature`
    params_to_kw_assignment_mode = get_signature_params(func_signature)
    params_names = list(params_to_kw_assignment_mode.keys())

    # Note: in decorator the annotations were extracted using getattr(func_impl, '__annotations__') instead.
    # This seems equivalent but more general (provided by the signature, not the function), but to check
    annotations, defaults, kwonlydefaults = get_signature_details(func_signature)

    # create the body of the function to compile
    # The generated function body should dispatch its received arguments to the inner function.
    # For this we will pass as much as possible the arguments as keywords.
    # However if there are varpositional arguments we cannot
    assignments = [("%s=%s" % (k, k)) if is_kw else k for k, is_kw in params_to_kw_assignment_mode.items()]
    params_str = ', '.join(assignments)
    if inject_as_first_arg:
        params_str = "%s, %s" % (func_name, params_str)

    if _is_generator_func(func_impl):
        if sys.version_info >= (3, 3):
            body = "def %s\n    yield from _func_impl_(%s)\n" % (func_signature_str, params_str)
        else:
            from makefun._main_legacy_py import get_legacy_py_generator_body_template
            body = get_legacy_py_generator_body_template() % (func_signature_str, params_str)
    elif isasyncgenfunction(func_impl):
        body = "async def %s\n    async for y in _func_impl_(%s):\n        yield y\n" % (func_signature_str, params_str)
    elif create_lambda:
        if func_signature_str:
            body = "lambda_ = lambda %s: _func_impl_(%s)\n" % (func_signature_str, params_str)
        else:
            body = "lambda_ = lambda: _func_impl_(%s)\n" % (params_str)
    else:
        body = "def %s\n    return _func_impl_(%s)\n" % (func_signature_str, params_str)

    if iscoroutinefunction(func_impl):
        body = ("async " + body).replace('return _func_impl_', 'return await _func_impl_')

    # create the function by compiling code, mapping the `_func_impl_` symbol to `func_impl`
    protect_eval_dict(evaldict, func_name, params_names)
    evaldict['_func_impl_'] = func_impl
    if create_lambda:
        f = _make("lambda_", params_names, body, evaldict)
    else:
        f = _make(co_name, params_names, body, evaldict)

    # add the source annotation if needed
    if add_source:
        attrs['__source__'] = body

    # add the handler if needed
    if add_impl:
        attrs['__func_impl__'] = func_impl

    # update the signature
    _update_fields(f, name=func_name, qualname=qualname, doc=doc, annotations=annotations,
                   defaults=tuple(defaults), kwonlydefaults=kwonlydefaults,
                   module=module_name, kw=attrs)

    return f


def _is_generator_func(func_impl):
    """
    Return True if the func_impl is a generator
    :param func_impl:
    :return:
    """
    if (3, 5) <= sys.version_info < (3, 6):
        # with Python 3.5 isgeneratorfunction returns True for all coroutines
        # however we know that it is NOT possible to have a generator
        # coroutine in python 3.5: PEP525 was not there yet
        return isgeneratorfunction(func_impl) and not iscoroutinefunction(func_impl)
    else:
        return isgeneratorfunction(func_impl)


def _is_lambda_func_name(func_name):
    """
    Return True if func_name is the name of a lambda
    :param func_name:
    :return:
    """
    return func_name == (lambda: None).__code__.co_name


def _is_valid_func_def_name(func_name):
    """
    Return True if func_name is valid in a function definition.
    :param func_name:
    :return:
    """
    return is_identifier(func_name) and not iskeyword(func_name)


class _SymbolRef:
    """
    A class used to protect signature default values and type hints when the local context would not be able
    to evaluate them properly when the new function is created. In this case we store them under a known name,
    we add that name to the locals(), and we use this symbol that has a repr() equal to the name.
    """
    __slots__ = 'varname'

    def __init__(self, varname):
        self.varname = varname

    def __repr__(self):
        return self.varname


def get_signature_string(func_name, func_signature, evaldict):
    """
    Returns the string to be used as signature.
    If there is a non-native symbol in the defaults, it is created as a variable in the evaldict
    :param func_name:
    :param func_signature:
    :return:
    """
    no_type_hints_allowed = sys.version_info < (3, 5)

    # protect the parameters if needed
    new_params = []
    params_changed = False
    for p_name, p in func_signature.parameters.items():
        # if default value can not be evaluated, protect it
        default_needs_protection = _signature_symbol_needs_protection(p.default, evaldict)
        new_default = _protect_signature_symbol(p.default, default_needs_protection, "DEFAULT_%s" % p_name, evaldict)

        if no_type_hints_allowed:
            new_annotation = Parameter.empty
            annotation_needs_protection = new_annotation is not p.annotation
        else:
            # if type hint can not be evaluated, protect it
            annotation_needs_protection = _signature_symbol_needs_protection(p.annotation, evaldict)
            new_annotation = _protect_signature_symbol(p.annotation, annotation_needs_protection, "HINT_%s" % p_name,
                                                       evaldict)

        # only create if necessary (inspect __init__ methods are slow)
        if default_needs_protection or annotation_needs_protection:
            # replace the parameter with the possibly new default and hint
            p = Parameter(p.name, kind=p.kind, default=new_default, annotation=new_annotation)
            params_changed = True

        new_params.append(p)

    if no_type_hints_allowed:
        new_return_annotation = Parameter.empty
        return_needs_protection = new_return_annotation is not func_signature.return_annotation
    else:
        # if return type hint can not be evaluated, protect it
        return_needs_protection = _signature_symbol_needs_protection(func_signature.return_annotation, evaldict)
        new_return_annotation = _protect_signature_symbol(func_signature.return_annotation, return_needs_protection,
                                                          "RETURNHINT", evaldict)

    # only create new signature if necessary (inspect __init__ methods are slow)
    if params_changed or return_needs_protection:
        s = Signature(parameters=new_params, return_annotation=new_return_annotation)
    else:
        s = func_signature

    # return the final string representation
    return "%s%s:" % (func_name, s)


def get_lambda_argument_string(func_signature, evaldict):
    """
    Returns the string to be used as arguments in a lambda function definition.
    If there is a non-native symbol in the defaults, it is created as a variable in the evaldict
    :param func_name:
    :param func_signature:
    :return:
    """
    return get_signature_string('', func_signature, evaldict)[1:-2]


TYPES_WITH_SAFE_REPR = (int, str, bytes, bool)
# IMPORTANT note: float is not in the above list because not all floats have a repr that is valid for the
# compiler: float('nan'), float('-inf') and float('inf') or float('+inf') have an invalid repr.


def _signature_symbol_needs_protection(symbol, evaldict):
    """
    Helper method for signature symbols (defaults, type hints) protection.

    Returns True if the given symbol needs to be protected - that is, if its repr() can not be correctly evaluated with
    current evaldict.

    :param symbol:
    :return:
    """
    if symbol is not None and symbol is not Parameter.empty and type(symbol) not in TYPES_WITH_SAFE_REPR:
        try:
            # check if the repr() of the default value is equal to itself.
            return eval(repr(symbol), evaldict) != symbol  # noqa  # we cannot use ast.literal_eval, too restrictive
        except Exception:
            # in case of error this needs protection
            return True
    else:
        return False


def _protect_signature_symbol(val, needs_protection, varname, evaldict):
    """
    Helper method for signature symbols (defaults, type hints) protection.

    Returns either `val`, or a protection symbol. In that case the protection symbol
    is created with name `varname` and inserted into `evaldict`

    :param val:
    :param needs_protection:
    :param varname:
    :param evaldict:
    :return:
    """
    if needs_protection:
        # store the object in the evaldict and insert name
        evaldict[varname] = val
        return _SymbolRef(varname)
    else:
        return val


def get_signature_from_string(func_sig_str, evaldict):
    """
    Creates a `Signature` object from the given function signature string.

    :param func_sig_str:
    :return: (func_name, func_sig, func_sig_str). func_sig_str is guaranteed to contain the ':' symbol already
    """
    # escape leading newline characters
    if func_sig_str.startswith('\n'):
        func_sig_str = func_sig_str[1:]

    # match the provided signature. note: fullmatch is not supported in python 2
    def_match = FUNC_DEF.match(func_sig_str)
    if def_match is None:
        raise SyntaxError('The provided function template is not valid: "%s" does not match '
                          '"<func_name>(<func_args>)[ -> <return-hint>]".\n For information the regex used is: "%s"'
                          '' % (func_sig_str, FUNC_DEF.pattern))
    groups = def_match.groupdict()

    # extract function name and parameter names list
    func_name = groups['funcname']
    if func_name is None or func_name == '':
        func_name_ = 'dummy'
        func_name = None
    else:
        func_name_ = func_name
    # params_str = groups['params']
    # params_names = extract_params_names(params_str)

    # find the keyword parameters and the others
    # posonly_names, kwonly_names, unrestricted_names = separate_positional_and_kw(params_names)

    colon_end = groups['colon']
    cmt_return_hint = groups['comment_return_hint']
    if (colon_end is None or len(colon_end) == 0) \
            and (cmt_return_hint is None or len(cmt_return_hint) == 0):
        func_sig_str = func_sig_str + ':'

    # Create a dummy function
    # complete the string if name is empty, so that we can actually use _make
    func_sig_str_ = (func_name_ + func_sig_str) if func_name is None else func_sig_str
    body = 'def %s\n    pass\n' % func_sig_str_
    dummy_f = _make(func_name_, [], body, evaldict)

    # return its signature
    return func_name, signature(dummy_f), func_sig_str


# def extract_params_names(params_str):
#     return [m.groupdict()['name'] for m in PARAM_DEF.finditer(params_str)]


# def separate_positional_and_kw(params_names):
#     """
#     Extracts the names that are positional-only, keyword-only, or non-constrained
#     :param params_names:
#     :return:
#     """
#     # by default all parameters can be passed as positional or keyword
#     posonly_names = []
#     kwonly_names = []
#     other_names = params_names
#
#     # but if we find explicit separation we have to change our mind
#     for i in range(len(params_names)):
#         name = params_names[i]
#         if name == '*':
#             del params_names[i]
#             posonly_names = params_names[0:i]
#             kwonly_names = params_names[i:]
#             other_names = []
#             break
#         elif name[0] == '*' and name[1] != '*':  #
#             # that's a *args. Next one will be keyword-only
#             posonly_names = params_names[0:(i + 1)]
#             kwonly_names = params_names[(i + 1):]
#             other_names = []
#             break
#         else:
#             # continue
#             pass
#
#     return posonly_names, kwonly_names, other_names


def get_signature_params(s):
    """
    Utility method to return the parameter names in the provided `Signature` object, by group of kind

    :param s:
    :return:
    """
    # this ordered dictionary will contain parameters and True/False whether we should use keyword assignment or not
    params_to_assignment_mode = OrderedDict()
    for p_name, p in s.parameters.items():
        if p.kind is Parameter.POSITIONAL_ONLY:
            params_to_assignment_mode[p_name] = False
        elif p.kind is Parameter.KEYWORD_ONLY:
            params_to_assignment_mode[p_name] = True
        elif p.kind is Parameter.POSITIONAL_OR_KEYWORD:
            params_to_assignment_mode[p_name] = True
        elif p.kind is Parameter.VAR_POSITIONAL:
            # We have to pass all the arguments that were here in previous positions, as positional too.
            for k in params_to_assignment_mode.keys():
                params_to_assignment_mode[k] = False
            params_to_assignment_mode["*" + p_name] = False
        elif p.kind is Parameter.VAR_KEYWORD:
            params_to_assignment_mode["**" + p_name] = False
        else:
            raise ValueError("Unknown kind: %s" % p.kind)

    return params_to_assignment_mode


def get_signature_details(s):
    """
    Utility method to extract the annotations, defaults and kwdefaults from a `Signature` object

    :param s:
    :return:
    """
    annotations = dict()
    defaults = []
    kwonlydefaults = dict()
    if s.return_annotation is not s.empty:
        annotations['return'] = s.return_annotation
    for p_name, p in s.parameters.items():
        if p.annotation is not s.empty:
            annotations[p_name] = p.annotation
        if p.default is not s.empty:
            # if p_name not in kwonly_names:
            if p.kind is not Parameter.KEYWORD_ONLY:
                defaults.append(p.default)
            else:
                kwonlydefaults[p_name] = p.default
    return annotations, defaults, kwonlydefaults


def extract_module_and_evaldict(frame):
    """
    Utility function to extract the module name from the given frame,
    and to return a dictionary containing globals and locals merged together

    :param frame:
    :return:
    """
    try:
        # get the module name
        module_name = frame.f_globals.get('__name__', '?')

        # construct a dictionary with all variables
        # this is required e.g. if a symbol is used in a type hint
        evaldict = copy(frame.f_globals)
        evaldict.update(frame.f_locals)

    except AttributeError:
        # either the frame is None of the f_globals and f_locals are not available
        module_name = '?'
        evaldict = dict()

    return evaldict, module_name


def protect_eval_dict(evaldict, func_name, params_names):
    """
    remove all symbols that could be harmful in evaldict

    :param evaldict:
    :param func_name:
    :param params_names:
    :return:
    """
    try:
        del evaldict[func_name]
    except KeyError:
        pass
    for n in params_names:
        try:
            del evaldict[n]
        except KeyError:
            pass

    return evaldict


# Atomic get-and-increment provided by the GIL
_compile_count = itertools.count()


def _make(funcname, params_names, body, evaldict=None):
    """
    Make a new function from a given template and update the signature

    :param func_name:
    :param params_names:
    :param body:
    :param evaldict:
    :param add_source:
    :return:
    """
    evaldict = evaldict or {}
    for n in params_names:
        if n in ('_func_', '_func_impl_'):
            raise NameError('%s is overridden in\n%s' % (n, body))

    if not body.endswith('\n'):  # newline is needed for old Pythons
        raise ValueError("body should end with a newline")

    # Ensure each generated function has a unique filename for profilers
    # (such as cProfile) that depend on the tuple of (<filename>,
    # <definition line>, <function name>) being unique.
    filename = '<makefun-gen-%d>' % (next(_compile_count),)
    try:
        code = compile(body, filename, 'single')
        exec(code, evaldict)  # noqa
    except BaseException:
        print('Error in generated code:', file=sys.stderr)
        print(body, file=sys.stderr)
        raise

    # extract the function from compiled code
    func = evaldict[funcname]

    return func


def _update_fields(
        func, name, qualname=None, doc=None, annotations=None, defaults=(), kwonlydefaults=None, module=None, kw=None
):
    """
    Update the signature of func with the provided information

    This method merely exists to remind which field have to be filled.

    :param func:
    :param name:
    :param qualname:
    :param kw:
    :return:
    """
    if kw is None:
        kw = dict()

    func.__name__ = name

    if qualname is not None:
        func.__qualname__ = qualname

    func.__doc__ = doc
    func.__dict__ = kw

    func.__defaults__ = defaults
    if len(kwonlydefaults) == 0:
        kwonlydefaults = None
    func.__kwdefaults__ = kwonlydefaults

    func.__annotations__ = annotations
    func.__module__ = module


def _get_callerframe(offset=0):
    try:
        # inspect.stack is extremely slow, the fastest is sys._getframe or inspect.currentframe().
        # See https://gist.github.com/JettJones/c236494013f22723c1822126df944b12
        frame = sys._getframe(2 + offset)
        # frame = currentframe()
        # for _ in range(2 + offset):
        #     frame = frame.f_back

    except AttributeError:  # for IronPython and similar implementations
        frame = None

    return frame


def wraps(wrapped_fun,
          new_sig=None,               # type: Union[str, Signature]
          prepend_args=None,          # type: Union[str, Parameter, Iterable[Union[str, Parameter]]]
          append_args=None,           # type: Union[str, Parameter, Iterable[Union[str, Parameter]]]
          remove_args=None,           # type: Union[str, Iterable[str]]
          func_name=None,             # type: str
          co_name=None,               # type: str
          inject_as_first_arg=False,  # type: bool
          add_source=True,            # type: bool
          add_impl=True,              # type: bool
          doc=None,                   # type: str
          qualname=None,              # type: str
          module_name=None,           # type: str
          **attrs
          ):
    """
    A decorator to create a signature-preserving wrapper function.

    It is similar to `functools.wraps`, but

     - relies on a proper dynamically-generated function. Therefore as opposed to `functools.wraps`,

        - the wrapper body will not be executed if the arguments provided are not compliant with the signature -
          instead a `TypeError` will be raised before entering the wrapper body.
        - the arguments will always be received as keywords by the wrapper, when possible. See
          [documentation](./index.md#signature-preserving-function-wrappers) for details.

     - you can modify the signature of the resulting function, by providing a new one with `new_sig` or by providing a
       list of arguments to remove in `remove_args`, to prepend in `prepend_args`, or to append in `append_args`.
       See [documentation](./index.md#editing-a-signature) for details.

    Comparison with `@with_signature`:`@wraps(f)` is equivalent to

        `@with_signature(signature(f),
                         func_name=f.__name__,
                         doc=f.__doc__,
                         module_name=f.__module__,
                         qualname=f.__qualname__,
                         __wrapped__=f,
                         **f.__dict__,
                         **attrs)`

    In other words, as opposed to `@with_signature`, the metadata (doc, module name, etc.) is provided by the wrapped
    `wrapped_fun`, so that the created function seems to be identical (except possibly for the signature).
    Note that all options in `with_signature` can still be overridden using parameters of `@wraps`.

    The additional `__wrapped__` attribute is set on the created function, to stay consistent
    with the `functools.wraps` behaviour. If the signature is modified through `new_sig`,
    `remove_args`, `append_args` or `prepend_args`, the additional
    `__signature__` attribute will be set so that `inspect.signature` and related functionality
    works as expected. See PEP 362 for more detail on `__wrapped__` and `__signature__`.

    See also [python documentation on @wraps](https://docs.python.org/3/library/functools.html#functools.wraps)

    :param wrapped_fun: the function that you intend to wrap with the decorated function. As in `functools.wraps`,
        `wrapped_fun` is used as the default reference for the exposed signature, `__name__`, `__qualname__`, `__doc__`
        and `__dict__`.
    :param new_sig: the new signature of the decorated function. By default it is `None` and means "same signature as
        in `wrapped_fun`" (similar behaviour as in `functools.wraps`). If you wish to modify the exposed signature
        you can either use `remove/prepend/append_args`, or pass a non-None `new_sig`. It can be either a string
        without 'def' such as "foo(a, b: int, *args, **kwargs)" of "(a, b: int)", or a `Signature` object, for example
        from the output of `inspect.signature` or from the `funcsigs.signature` backport. Note that these objects can
        be created manually too. If the signature is provided as a string and contains a non-empty name, this name
        will be used instead of the one of `wrapped_fun`.
    :param prepend_args: a string or list of strings to prepend to the signature of `wrapped_fun`. These extra arguments
        should not be passed to `wrapped_fun`, as it does not know them. This is typically used to easily create a
        wrapper with additional arguments, without having to manipulate the signature objects.
    :param append_args: a string or list of strings to append to the signature of `wrapped_fun`. These extra arguments
        should not be passed to `wrapped_fun`, as it does not know them. This is typically used to easily create a
        wrapper with additional arguments, without having to manipulate the signature objects.
    :param remove_args: a string or list of strings to remove from the signature of `wrapped_fun`. These arguments
        should be injected in the received `kwargs` before calling `wrapped_fun`, as it requires them. This is typically
        used to easily create a wrapper with less arguments, without having to manipulate the signature objects.
    :param func_name: provide a non-`None` value to override the created function `__name__` and `__qualname__`. If this
        is `None` (default), the `__name__` will default to the ones of `wrapped_fun` if `new_sig` is `None` or is a
        `Signature`, or to the name defined in `new_sig` if `new_sig` is a `str` and contains a non-empty name.
    :param inject_as_first_arg: if `True`, the created function will be injected as the first positional argument of
        the decorated function. This can be handy in case the implementation is shared between several facades and needs
        to know from which context it was called. Default=`False`
    :param add_source: a boolean indicating if a '__source__' annotation should be added to the generated function
        (default: True)
    :param add_impl: a boolean indicating if a '__func_impl__' annotation should be added to the generated function
        (default: True)
    :param doc: a string representing the docstring that will be used to set the __doc__ attribute on the generated
        function. If None (default), the doc of `wrapped_fun` will be used. If `wrapped_fun` is an instance of
        `functools.partial`, a special enhanced doc will be generated.
    :param qualname: a string representing the qualified name to be used. If None (default), the `__qualname__` will
        default to the one of `wrapped_fun`, or the one in `new_sig` if `new_sig` is provided as a string with a
        non-empty function name.
    :param co_name: a string representing the name to be used in the compiled code of the function. If None (default),
        the `__code__.co_name` will default to the one of `func_impl` if `func_signature` is a `Signature`, or to the
        name defined in `func_signature` if `func_signature` is a `str` and contains a non-empty name.
    :param module_name: the name of the module to be set on the function (under __module__ ). If None (default), the
        `__module__` attribute of `wrapped_fun` will be used.
    :param attrs: other keyword attributes that should be set on the function. Note that the full `__dict__` of
        `wrapped_fun` is automatically copied.
    :return: a decorator
    """
    func_name, func_sig, doc, qualname, co_name, module_name, all_attrs = _get_args_for_wrapping(wrapped_fun, new_sig,
                                                                                                 remove_args,
                                                                                                 prepend_args,
                                                                                                 append_args,
                                                                                                 func_name, doc,
                                                                                                 qualname, co_name,
                                                                                                 module_name, attrs)

    return with_signature(func_sig,
                          func_name=func_name,
                          inject_as_first_arg=inject_as_first_arg,
                          add_source=add_source, add_impl=add_impl,
                          doc=doc,
                          qualname=qualname,
                          co_name=co_name,
                          module_name=module_name,
                          **all_attrs)


def _get_args_for_wrapping(wrapped, new_sig, remove_args, prepend_args, append_args,
                           func_name, doc, qualname, co_name, module_name, attrs):
    """
    Internal method used by @wraps and create_wrapper

    :param wrapped:
    :param new_sig:
    :param remove_args:
    :param prepend_args:
    :param append_args:
    :param func_name:
    :param doc:
    :param qualname:
    :param co_name:
    :param module_name:
    :param attrs:
    :return:
    """
    # the desired signature
    has_new_sig = False
    if new_sig is not None:
        if remove_args is not None or prepend_args is not None or append_args is not None:
            raise ValueError("Only one of `[remove/prepend/append]_args` or `new_sig` should be provided")
        func_sig = new_sig
        has_new_sig = True
    else:
        func_sig = signature(wrapped)
        if remove_args:
            if isinstance(remove_args, string_types):
                remove_args = (remove_args,)
            func_sig = remove_signature_parameters(func_sig, *remove_args)
            has_new_sig = True

        if prepend_args:
            if isinstance(prepend_args, string_types):
                prepend_args = (prepend_args,)
        else:
            prepend_args = ()

        if append_args:
            if isinstance(append_args, string_types):
                append_args = (append_args,)
        else:
            append_args = ()

        if prepend_args or append_args:
            has_new_sig = True
            func_sig = add_signature_parameters(func_sig, first=prepend_args, last=append_args)

    # the desired metadata
    if func_name is None:
        func_name = getattr_partial_aware(wrapped, '__name__', None)
    if doc is None:
        doc = getattr(wrapped, '__doc__', None)
        if isinstance(wrapped, functools.partial) and not has_new_sig \
                and doc == functools.partial(lambda: True).__doc__:
            # the default generic partial doc. Generate a better doc, since we know that the sig is not messed with
            orig_sig = signature(wrapped.func)
            doc = gen_partial_doc(getattr_partial_aware(wrapped.func, '__name__', None),
                                  getattr_partial_aware(wrapped.func, '__doc__', None),
                                  orig_sig, func_sig, wrapped.args)
    if qualname is None:
        qualname = getattr_partial_aware(wrapped, '__qualname__', None)
    if module_name is None:
        module_name = getattr_partial_aware(wrapped, '__module__', None)
    if co_name is None:
        code = getattr_partial_aware(wrapped, '__code__', None)
        if code is not None:
            co_name = code.co_name

    # attributes: start from the wrapped dict, add '__wrapped__' if needed, and override with all attrs.
    all_attrs = copy(getattr_partial_aware(wrapped, '__dict__'))
    # PEP362: always set `__wrapped__`, and if signature was changed, set `__signature__` too
    all_attrs["__wrapped__"] = wrapped
    if has_new_sig:
        if isinstance(func_sig, Signature):
            all_attrs["__signature__"] = func_sig
        else:
            # __signature__ must be a Signature object, so if it is a string we need to evaluate it.
            frame = _get_callerframe(offset=1)
            evaldict, _ = extract_module_and_evaldict(frame)
            # Here we could wish to directly override `func_name` and `func_sig` so that this does not have to be done
            # again by `create_function` later... Would this be risky ?
            _func_name, func_sig_as_sig, _ = get_signature_from_string(func_sig, evaldict)
            all_attrs["__signature__"] = func_sig_as_sig

    all_attrs.update(attrs)

    return func_name, func_sig, doc, qualname, co_name, module_name, all_attrs


def with_signature(func_signature,             # type: Union[str, Signature]
                   func_name=None,             # type: str
                   inject_as_first_arg=False,  # type: bool
                   add_source=True,             # type: bool
                   add_impl=True,            # type: bool
                   doc=None,                   # type: str
                   qualname=None,              # type: str
                   co_name=None,                # type: str
                   module_name=None,            # type: str
                   **attrs
                   ):
    """
    A decorator for functions, to change their signature. The new signature should be compliant with the old one.

    ```python
    @with_signature(<arguments>)
    def impl(...):
        ...
    ```

    is totally equivalent to `impl = create_function(<arguments>, func_impl=impl)` except for one additional behaviour:

     - If `func_signature` is set to `None`, there is no `TypeError` as in create_function. Instead, this simply
     applies the new metadata (name, doc, module_name, attrs) to the decorated function without creating a wrapper.
     `add_source`, `add_impl` and `inject_as_first_arg` should not be set in this case.

    :param func_signature: the new signature of the decorated function. Either a string without 'def' such as
        "foo(a, b: int, *args, **kwargs)" of "(a, b: int)", or a `Signature` object, for example from the output of
        `inspect.signature` or from the `funcsigs.signature` backport. Note that these objects can be created manually
        too. If the signature is provided as a string and contains a non-empty name, this name will be used instead
        of the one of the decorated function. Finally `None` can be provided to indicate that user wants to only change
        the medatadata (func_name, doc, module_name, attrs) of the decorated function, without generating a new
        function.
    :param inject_as_first_arg: if `True`, the created function will be injected as the first positional argument of
        the decorated function. This can be handy in case the implementation is shared between several facades and needs
        to know from which context it was called. Default=`False`
    :param func_name: provide a non-`None` value to override the created function `__name__` and `__qualname__`. If this
        is `None` (default), the `__name__` will default to the ones of the decorated function if `func_signature` is a
        `Signature`, or to the name defined in `func_signature` if `func_signature` is a `str` and contains a non-empty
        name.
    :param add_source: a boolean indicating if a '__source__' annotation should be added to the generated function
        (default: True)
    :param add_impl: a boolean indicating if a '__func_impl__' annotation should be added to the generated function
        (default: True)
    :param doc: a string representing the docstring that will be used to set the __doc__ attribute on the generated
        function. If None (default), the doc of the decorated function will be used.
    :param qualname: a string representing the qualified name to be used. If None (default), the `__qualname__` will
        default to the one of `func_impl` if `func_signature` is a `Signature`, or to the name defined in
        `func_signature` if `func_signature` is a `str` and contains a non-empty name.
    :param co_name: a string representing the name to be used in the compiled code of the function. If None (default),
        the `__code__.co_name` will default to the one of `func_impl` if `func_signature` is a `Signature`, or to the
        name defined in `func_signature` if `func_signature` is a `str` and contains a non-empty name.
    :param module_name: the name of the module to be set on the function (under __module__ ). If None (default), the
        `__module__` attribute of the decorated function will be used.
    :param attrs: other keyword attributes that should be set on the function. Note that the full `__dict__` of the
        decorated function is not automatically copied.
    """
    if func_signature is None and co_name is None:
        # make sure that user does not provide non-default other args
        if inject_as_first_arg or not add_source or not add_impl:
            raise ValueError("If `func_signature=None` no new signature will be generated so only `func_name`, "
                             "`module_name`, `doc` and `attrs` should be provided, to modify the metadata.")
        else:
            def replace_f(f):
                # manually apply all the non-None metadata, but do not call create_function - that's useless
                if func_name is not None:
                    f.__name__ = func_name
                if doc is not None:
                    f.__doc__ = doc
                if qualname is not None:
                    f.__qualname__ = qualname
                if module_name is not None:
                    f.__module__ = module_name
                for k, v in attrs.items():
                    setattr(f, k, v)
                return f
    else:
        def replace_f(f):
            return create_function(func_signature=func_signature,
                                   func_impl=f,
                                   func_name=func_name,
                                   inject_as_first_arg=inject_as_first_arg,
                                   add_source=add_source,
                                   add_impl=add_impl,
                                   doc=doc,
                                   qualname=qualname,
                                   co_name=co_name,
                                   module_name=module_name,
                                   _with_sig_=True,  # special trick to tell create_function that we're @with_signature
                                   **attrs
                                   )

    return replace_f


def remove_signature_parameters(s,
                                *param_names):
    """
    Removes the provided parameters from the signature `s` (returns a new `Signature` instance).

    :param s:
    :param param_names: a list of parameter names to remove
    :return:
    """
    params = OrderedDict(s.parameters.items())
    for param_name in param_names:
        del params[param_name]
    return s.replace(parameters=params.values())


def add_signature_parameters(s,             # type: Signature
                             first=(),      # type: Union[str, Parameter, Iterable[Union[str, Parameter]]]
                             last=(),       # type: Union[str, Parameter, Iterable[Union[str, Parameter]]]
                             custom=(),     # type: Union[Parameter, Iterable[Parameter]]
                             custom_idx=-1  # type: int
                             ):
    """
    Adds the provided parameters to the signature `s` (returns a new `Signature` instance).

    :param s: the original signature to edit
    :param first: a single element or a list of `Parameter` instances to be added at the beginning of the parameter's
        list. Strings can also be provided, in which case the parameter kind will be created based on best guess.
    :param last: a single element or a list of `Parameter` instances to be added at the end of the parameter's list.
        Strings can also be provided, in which case the parameter kind will be created based on best guess.
    :param custom: a single element or a list of `Parameter` instances to be added at a custom position in the list.
        That position is determined with `custom_idx`
    :param custom_idx: the custom position to insert the `custom` parameters to.
    :return: a new signature created from the original one by adding the specified parameters.
    """
    params = OrderedDict(s.parameters.items())
    lst = list(params.values())

    # insert at custom position (but keep the order, that's why we use 'reversed')
    try:
        for param in reversed(custom):
            if param.name in params:
                raise ValueError("Parameter with name '%s' is present twice in the signature to create" % param.name)
            else:
                lst.insert(custom_idx, param)
    except TypeError:
        # a single argument
        if custom.name in params:
            raise ValueError("Parameter with name '%s' is present twice in the signature to create" % custom.name)
        else:
            lst.insert(custom_idx, custom)

    # prepend but keep the order
    first_param_kind = None
    try:
        for param in reversed(first):
            if isinstance(param, string_types):
                # Create a Parameter with auto-guessed 'kind'
                if first_param_kind is None:
                    # by default use this
                    first_param_kind = Parameter.POSITIONAL_OR_KEYWORD
                    try:
                        # check the first parameter kind
                        first_param_kind = next(iter(params.values())).kind
                    except StopIteration:
                        # no parameter - ok
                        pass
                # if the first parameter is a pos-only or a varpos we have to change to pos only.
                if first_param_kind in (Parameter.POSITIONAL_ONLY, Parameter.VAR_POSITIONAL):
                    first_param_kind = Parameter.POSITIONAL_ONLY
                param = Parameter(name=param, kind=first_param_kind)
            else:
                # remember the kind
                first_param_kind = param.kind

            if param.name in params:
                raise ValueError("Parameter with name '%s' is present twice in the signature to create" % param.name)
            else:
                lst.insert(0, param)
    except TypeError:
        # a single argument
        if first.name in params:
            raise ValueError("Parameter with name '%s' is present twice in the signature to create" % first.name)
        else:
            lst.insert(0, first)

    # append
    last_param_kind = None
    try:
        for param in last:
            if isinstance(param, string_types):
                # Create a Parameter with auto-guessed 'kind'
                if last_param_kind is None:
                    # by default use this
                    last_param_kind = Parameter.POSITIONAL_OR_KEYWORD
                    try:
                        # check the last parameter kind
                        last_param_kind = next(reversed(params.values())).kind
                    except StopIteration:
                        # no parameter - ok
                        pass
                # if the last parameter is a keyword-only or a varkw we have to change to kw only.
                if last_param_kind in (Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD):
                    last_param_kind = Parameter.KEYWORD_ONLY
                param = Parameter(name=param, kind=last_param_kind)
            else:
                # remember the kind
                last_param_kind = param.kind

            if param.name in params:
                raise ValueError("Parameter with name '%s' is present twice in the signature to create" % param.name)
            else:
                lst.append(param)
    except TypeError:
        # a single argument
        if last.name in params:
            raise ValueError("Parameter with name '%s' is present twice in the signature to create" % last.name)
        else:
            lst.append(last)

    return s.replace(parameters=lst)


def with_partial(*preset_pos_args, **preset_kwargs):
    """
    Decorator to 'partialize' a function using `partial`

    :param preset_pos_args:
    :param preset_kwargs:
    :return:
    """
    def apply_decorator(f):
        return partial(f, *preset_pos_args, **preset_kwargs)
    return apply_decorator


def partial(f,                 # type: Callable
            *preset_pos_args,  # type: Any
            **preset_kwargs    # type: Any
            ):
    """
    Equivalent of `functools.partial` but relies on a dynamically-created function. As a result the function
    looks nicer to users in terms of apparent documentation, name, etc.

    See [documentation](./index.md#removing-parameters-easily) for details.

    :param preset_pos_args:
    :param preset_kwargs:
    :return:
    """
    # TODO do we need to mimic `partial`'s behaviour concerning positional args?

    # (1) remove/change all preset arguments from the signature
    orig_sig = signature(f)
    if preset_pos_args or preset_kwargs:
        new_sig = gen_partial_sig(orig_sig, preset_pos_args, preset_kwargs, f)
    else:
        new_sig = None

    if _is_generator_func(f):
        if sys.version_info >= (3, 3):
            from makefun._main_py35_and_higher import make_partial_using_yield_from
            partial_f = make_partial_using_yield_from(new_sig, f, *preset_pos_args, **preset_kwargs)
        else:
            from makefun._main_legacy_py import make_partial_using_yield
            partial_f = make_partial_using_yield(new_sig, f, *preset_pos_args, **preset_kwargs)
    elif isasyncgenfunction(f) and sys.version_info >= (3, 6):
        from makefun._main_py36_and_higher import make_partial_using_async_for_in_yield
        partial_f = make_partial_using_async_for_in_yield(new_sig, f, *preset_pos_args, **preset_kwargs)
    else:
        @wraps(f, new_sig=new_sig)
        def partial_f(*args, **kwargs):
            # since the signature does the checking for us, no need to check for redundancy.
            kwargs.update(preset_kwargs)
            return f(*itertools.chain(preset_pos_args, args), **kwargs)

    # update the doc.
    # Note that partial_f is generated above with a proper __name__ and __doc__ identical to the wrapped ones
    if new_sig is not None:
        partial_f.__doc__ = gen_partial_doc(partial_f.__name__, partial_f.__doc__, orig_sig, new_sig, preset_pos_args)

    # Set the func attribute as `functools.partial` does
    partial_f.func = f

    return partial_f


if PY2:
    # In python 2 keyword-only arguments do not exist.
    # so if they do not have a default value, we set them with a default value
    # that is this singleton. This is the only way we can have the same behaviour
    # in python 2 in terms of order of arguments, than what funcools.partial does.
    class KwOnly:
        def __str__(self):
            return repr(self)

        def __repr__(self):
            return "KW_ONLY_ARG!"

    KW_ONLY = KwOnly()
else:
    KW_ONLY = None


def gen_partial_sig(orig_sig,         # type: Signature
                    preset_pos_args,  # type: Tuple[Any]
                    preset_kwargs,    # type: Mapping[str, Any]
                    f,                # type: Callable
                    ):
    """
    Returns the signature of partial(f, *preset_pos_args, **preset_kwargs)
    Raises explicit errors in case of non-matching argument names.

    By default the behaviour is the same as `functools.partial`:

     - partialized positional arguments disappear from the signature
     - partialized keyword arguments remain in the signature in the same order, but all keyword arguments after them
       in the parameters order become keyword-only (if python 2, they do not become keyword-only as this is not allowed
       in the compiler, but we pass them a bad default value "KEYWORD_ONLY")

    :param orig_sig:
    :param preset_pos_args:
    :param preset_kwargs:
    :param f: used in error messages only
    :return:
    """
    preset_kwargs = copy(preset_kwargs)

    # remove the first n positional, and assign/change default values for the keyword
    if len(orig_sig.parameters) < len(preset_pos_args):
        raise ValueError("Cannot preset %s positional args, function %s has only %s args."
                         "" % (len(preset_pos_args), getattr(f, '__name__', f), len(orig_sig.parameters)))

    # then the keywords. If they have a new value override it
    new_params = []
    kwonly_flag = False
    for i, (p_name, p) in enumerate(orig_sig.parameters.items()):
        if i < len(preset_pos_args):
            # preset positional arg: disappears from signature
            continue
        try:
            # is this parameter overridden in `preset_kwargs` ?
            overridden_p_default = preset_kwargs.pop(p_name)
        except KeyError:
            # no: it will appear "as is" in the signature, in the same order

            # However we need to change the kind if the kind is not already "keyword only"
            # positional only:  Parameter.POSITIONAL_ONLY, VAR_POSITIONAL
            # both: POSITIONAL_OR_KEYWORD
            # keyword only: KEYWORD_ONLY, VAR_KEYWORD
            if kwonly_flag and p.kind not in (Parameter.VAR_KEYWORD, Parameter.KEYWORD_ONLY):
                if PY2:
                    # Special : we can not make if Keyword-only, but we can not leave it without default value
                    new_kind = p.kind
                    # set a default value of
                    new_default = p.default if p.default is not Parameter.empty else KW_ONLY
                else:
                    new_kind = Parameter.KEYWORD_ONLY
                    new_default = p.default
                p = Parameter(name=p.name, kind=new_kind, default=new_default, annotation=p.annotation)

        else:
            # yes: override definition with the default. Note that the parameter will remain in the signature
            # but as "keyword only" (and so will be all following args)
            if p.kind is Parameter.POSITIONAL_ONLY:
                raise NotImplementedError("Predefining a positional-only argument using keyword is not supported as in "
                                          "python 3.8.8, 'signature()' does not support such functions and raises a"
                                          "ValueError. Please report this issue if support needs to be added in the "
                                          "future.")

            if not PY2 and p.kind not in (Parameter.VAR_KEYWORD, Parameter.KEYWORD_ONLY):
                # change kind to keyword-only
                new_kind = Parameter.KEYWORD_ONLY
            else:
                new_kind = p.kind
            p = Parameter(name=p.name, kind=new_kind, default=overridden_p_default, annotation=p.annotation)

            # from now on, all other parameters need to be keyword-only
            kwonly_flag = True

        # preserve order
        new_params.append(p)

    new_sig = Signature(parameters=tuple(new_params),
                        return_annotation=orig_sig.return_annotation)

    if len(preset_kwargs) > 0:
        raise ValueError("Cannot preset keyword argument(s), not present in the signature of %s: %s"
                         "" % (getattr(f, '__name__', f), preset_kwargs))
    return new_sig


def gen_partial_doc(wrapped_name, wrapped_doc, orig_sig, new_sig, preset_pos_args):
    """
    Generate a documentation indicating which positional arguments and keyword arguments are set in this
    partial implementation, and appending the wrapped function doc.

    :param wrapped_name:
    :param wrapped_doc:
    :param orig_sig:
    :param new_sig:
    :param preset_pos_args:
    :return:
    """
    # generate the "equivalent signature": this is the original signature,
    # where all values injected by partial appear
    all_strs = []
    kw_only = False
    for i, (p_name, _p) in enumerate(orig_sig.parameters.items()):
        if i < len(preset_pos_args):
            # use the preset positional. Use repr() instead of str() so that e.g. "yes" appears with quotes
            all_strs.append(repr(preset_pos_args[i]))
        else:
            # use the one in the new signature
            pnew = new_sig.parameters[p_name]
            if not kw_only:
                if (PY2 and pnew.default is KW_ONLY) or pnew.kind == Parameter.KEYWORD_ONLY:
                    kw_only = True

            if PY2 and kw_only:
                all_strs.append(str(pnew).replace("=%s" % KW_ONLY, ""))
            else:
                all_strs.append(str(pnew))

    argstring = ", ".join(all_strs)

    # Write the final docstring
    if wrapped_doc is None or len(wrapped_doc) == 0:
        partial_doc = "<This function is equivalent to '%s(%s)'.>\n" % (wrapped_name, argstring)
    else:
        new_line = "<This function is equivalent to '%s(%s)', see original '%s' doc below.>\n" \
                   "" % (wrapped_name, argstring, wrapped_name)
        partial_doc = new_line + wrapped_doc

    return partial_doc


class UnsupportedForCompilation(TypeError):
    """
    Exception raised by @compile_fun when decorated target is not supported
    """
    pass


class UndefinedSymbolError(NameError):
    """
    Exception raised by @compile_fun when the function requires a name not yet defined
    """
    pass


class SourceUnavailable(OSError):
    """
    Exception raised by @compile_fun when the function source is not available (inspect.getsource raises an error)
    """
    pass


def compile_fun(recurse=True,     # type: Union[bool, Callable]
                except_names=(),  # type: Iterable[str]
                ):
    """
    A draft decorator to `compile` any existing function so that users cant
    debug through it. It can be handy to mask some code from your users for
    convenience (note that this does not provide any obfuscation, people can
    still reverse engineer your code easily. Actually the source code even gets
    copied in the function's `__source__` attribute for convenience):

    ```python
    from makefun import compile_fun

    @compile_fun
    def foo(a, b):
        return a + b

    assert foo(5, -5.0) == 0
    print(foo.__source__)
    ```

    yields

    ```
    @compile_fun
    def foo(a, b):
        return a + b
    ```

    If the function closure includes functions, they are recursively replaced with compiled versions too (only for
    this closure, this does not modify them otherwise).

    **IMPORTANT** this decorator is a "goodie" in early stage and has not been extensively tested. Feel free to
    contribute !

    Note that according to [this post](https://stackoverflow.com/a/471227/7262247) compiling does not make the code
    run any faster.

    Known issues: `NameError` will appear if your function code depends on symbols that have not yet been defined.
    Make sure all symbols exist first ! See https://github.com/smarie/python-makefun/issues/47

    :param recurse: a boolean (default `True`) indicating if referenced symbols should be compiled too
    :param except_names: an optional list of symbols to exclude from compilation when `recurse=True`
    :return:
    """
    if callable(recurse):
        # called with no-args, apply immediately
        target = recurse
        # noinspection PyTypeChecker
        return compile_fun_manually(target, _evaldict=True)
    else:
        # called with parenthesis, return a decorator
        def apply_compile_fun(target):
            return compile_fun_manually(target, recurse=recurse, except_names=except_names, _evaldict=True)

        return apply_compile_fun


def compile_fun_manually(target,
                         recurse=True,     # type: Union[bool, Callable]
                         except_names=(),  # type: Iterable[str]
                         _evaldict=None    # type: Union[bool, Dict]
                         ):
    """

    :param target:
    :return:
    """
    if not isinstance(target, FunctionType):
        raise UnsupportedForCompilation("Only functions can be compiled by this decorator")

    if _evaldict is None or _evaldict is True:
        if _evaldict is True:
            frame = _get_callerframe(offset=1)
        else:
            frame = _get_callerframe()
        _evaldict, _ = extract_module_and_evaldict(frame)

    # first make sure that source code is available for compilation
    try:
        lines = getsource(target)
    except (OSError, IOError) as e:  # noqa # distinct exceptions in old python versions
        if 'could not get source code' in str(e):
            raise SourceUnavailable(target, e)
        else:
            raise

    # compile all references first
    try:
        # python 3
        func_closure = target.__closure__
        func_code = target.__code__
    except AttributeError:
        # python 2
        func_closure = target.func_closure
        func_code = target.func_code

    # Does not work: if `self.i` is used in the code, `i` will appear here
    # if func_code is not None:
    #     for name in func_code.co_names:
    #         try:
    #             eval(name, _evaldict)
    #         except NameError:
    #             raise UndefinedSymbolError("Symbol `%s` does not seem to be defined yet. Make sure you apply "
    #                                        "`compile_fun` *after* all required symbols have been defined." % name)

    if recurse and func_closure is not None:
        # recurse-compile
        for name, cell in zip(func_code.co_freevars, func_closure):
            if name in except_names:
                continue
            if name not in _evaldict:
                raise UndefinedSymbolError("Symbol %s does not seem to be defined yet. Make sure you apply "
                                           "`compile_fun` *after* all required symbols have been defined." % name)
            try:
                value = cell.cell_contents
            except ValueError:
                # empty cell
                continue
            else:
                # non-empty cell
                try:
                    # note : not sure the compilation will be made in the appropriate order of dependencies...
                    # if not, users will have to do it manually
                    _evaldict[name] = compile_fun_manually(value,
                                                           recurse=recurse, except_names=except_names,
                                                           _evaldict=_evaldict)
                except (UnsupportedForCompilation, SourceUnavailable):
                    pass

    # now compile from sources
    lines = dedent(lines)
    source_lines = lines
    if lines.startswith('@compile_fun'):
        lines = '\n'.join(lines.splitlines()[1:])
    if '@compile_fun' in lines:
        raise ValueError("@compile_fun seems to appear several times in the function source")
    if lines[-1] != '\n':
        lines += '\n'
    # print("compiling: ")
    # print(lines)
    new_f = _make(target.__name__, (), lines, _evaldict)
    new_f.__source__ = source_lines

    return new_f
