# Authors: Sylvain MARIE <sylvain.marie@se.com>
#          + All contributors to <https://github.com/smarie/python-makefun>
#
# License: 3-clause BSD, <https://github.com/smarie/python-makefun/blob/master/LICENSE>
import sys
from itertools import chain

from makefun.main import wraps


def make_partial_using_yield(new_sig, f, *preset_pos_args, **preset_kwargs):
    """
    Makes a 'partial' when f is a generator and python is new enough to support `yield from`

    :param new_sig:
    :param f:
    :param preset_pos_args:
    :param preset_kwargs:
    :return:
    """
    @wraps(f, new_sig=new_sig)
    def partial_f(*args, **kwargs):
        # since the signature does the checking for us, no need to check for redundancy.
        kwargs.update(preset_kwargs)
        gen = f(*chain(preset_pos_args, args), **kwargs)
        _i = iter(gen)  # initialize the generator
        _y = next(_i)  # first iteration
        while 1:
            try:
                _s = yield _y  # yield the first output and retrieve the new input
            except GeneratorExit as _e:  # ---generator exit error---
                try:
                    _m = _i.close  # if there is a close method
                except AttributeError:
                    pass
                else:
                    _m()  # use it first
                raise _e  # then re-raise exception
            except BaseException as _e:  # ---other exception
                _x = sys.exc_info()  # if captured exception, grab info
                try:
                    _m = _i.throw  # if there is a throw method
                except AttributeError:
                    raise _e  # otherwise re-raise
                else:
                    _y = _m(*_x)  # use it
            else:  # --- nominal case: the new input was received
                # if _s is None:
                #     _y = next(_i)
                # else:
                _y = _i.send(_s)  # let the implementation decide if None means "no new input" or "new input = None"
    return partial_f


def get_legacy_py_generator_body_template():
    """
    In Python 2 we cannot use `yield from` in the generated function body.
    This is a replacement, from PEP380 - see https://www.python.org/dev/peps/pep-0380/#formal-semantics

    note: we removed a few lines so that `StopIteration` exceptions are re-raised
    :return:
    """
    return """def %s
    _i = iter(_func_impl_(%s))    # initialize the generator
    _y = next(_i)                    # first iteration
    while 1:
        try:
            _s = yield _y            # yield the first output and retrieve the new input
        except GeneratorExit as _e:  # ---generator exit error---
            try:
                _m = _i.close        # if there is a close method
            except AttributeError:
                pass
            else:
                _m()                 # use it first
            raise _e                 # then re-raise exception
        except BaseException as _e:  # ---other exception
            _x = sys.exc_info()      # if captured exception, grab info
            try:
                _m = _i.throw        # if there is a throw method
            except AttributeError:
                raise _e             # otherwise re-raise
            else:
                _y = _m(*_x)         # use it
        else:                        # --- nominal case: the new input was received
            # if _s is None:
            #     _y = next(_i)
            # else:
            _y = _i.send(_s)     # let the implementation decide if None means "no new input" or "new input = None"
"""
