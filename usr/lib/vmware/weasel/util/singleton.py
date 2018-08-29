class Singleton(object):
    '''Abstract base for any class that implements the Singleton design
    pattern.

    Child classes MUST implement a _singleton_init method.  This method
    will be called only once, when the singleton is first initialized. That
    way, you can initialize default values of attributes.  If you tried to
    initialize default values of attributes in __init__, the singleton would
    get clobbered on each constructor call.

    >>> class Foo(Singleton):
    ...    def _singleton_init(self):
    ...       self.shared_state = 0
    ...
    >>> a = Foo(); b = Foo()
    >>> a.shared_state += 1
    >>> b.shared_state
    1
    >>> a is b
    True

    >>> class Foo(Singleton):
    ...    def _singleton_init(self): pass
    ...    def __init__(self):
    ...       self.wrong_shared_state = 0 #should've gone in _singleton_init
    ...
    >>> a = Foo()
    >>> a.wrong_shared_state = 5
    >>> b = Foo() #clobbered!
    >>> a.wrong_shared_state, b.wrong_shared_state
    (0, 0)
    '''
    def __new__(cls, *p, **kw):
        if not '_the_only_instance' in cls.__dict__ or \
                not cls._the_only_instance:
            cls._the_only_instance = object.__new__(cls)
            if not '_singleton_init' in cls.__dict__:
                msg = 'Class '+ str(cls) +\
                      ' does not have the special _singleton_init function'
                raise NotImplementedError(msg)
            cls._singleton_init(cls._the_only_instance, *p, **kw)
        return cls._the_only_instance

