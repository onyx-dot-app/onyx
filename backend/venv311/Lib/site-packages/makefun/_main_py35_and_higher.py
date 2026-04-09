# Authors: Sylvain MARIE <sylvain.marie@se.com>
#          + All contributors to <https://github.com/smarie/python-makefun>
#
# License: 3-clause BSD, <https://github.com/smarie/python-makefun/blob/master/LICENSE>
from itertools import chain

from makefun.main import wraps


def make_partial_using_yield_from(new_sig, f, *preset_pos_args, **preset_kwargs):
    """
    Makes a 'partial' when f is a generator and python is new enough to support `yield from`

    :param new_sig:
    :param f:
    :param presets:
    :return:
    """
    @wraps(f, new_sig)
    def partial_f(*args, **kwargs):
        # since the signature does the checking for us, no need to check for redundancy.
        kwargs.update(preset_kwargs)  # for python 3.4: explicit dict update
        yield from f(*chain(preset_pos_args, args), **kwargs)
    return partial_f
