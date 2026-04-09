# Authors: Sylvain MARIE <sylvain.marie@se.com>
#          + All contributors to <https://github.com/smarie/python-makefun>
#
# License: 3-clause BSD, <https://github.com/smarie/python-makefun/blob/master/LICENSE>
from itertools import chain

from makefun.main import wraps


def make_partial_using_async_for_in_yield(new_sig, f, *preset_pos_args, **preset_kwargs):
    """
    Makes a 'partial' when f is a async generator and python is new enough to support `async for v in f(): yield v`

    :param new_sig:
    :param f:
    :param presets:
    :return:
    """

    @wraps(f, new_sig=new_sig)
    async def partial_f(*args, **kwargs):
        kwargs.update(preset_kwargs)
        async for v in f(*chain(preset_pos_args, args), **kwargs):
            yield v

    return partial_f
