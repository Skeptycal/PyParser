#!/usr/bin/env python
# Copyright (c) 2012, 2013, Andrew Carter
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met: 
#
# 1. Redistributions of source code must retain the above copyright notice, this
#  list of conditions and the following disclaimer. 
# 2. Redistributions in binary form must reproduce the above copyright notice,
#  this list of conditions and the following disclaimer in the documentation
#  and/or other materials provided with the distribution. 
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation are those
# of the authors and should not be interpreted as representing official policies, 
# either expressed or implied, of the FreeBSD Project.

def private():
  from copy import copy
  from itertools import chain
  from functools import partial
  from queue import PriorityQueue
  from sys import stderr
  from ._util import begins, fork, identity, tailEval, badcall
  
  DEBUGGING = None
  def DEBUG(self, input, **kwargs):
    nonlocal DEBUGGING
    if DEBUGGING:
      input = list(input.fork())
      print("DEBUG : %s >> %s" % (input, self), file=DEBUGGING)
  def ASSERTEQ(a, b):
    if DEBUGGING and not a == b:
      print("%s != %s" % (a, b), file=DEBUGGING)
    assert(a == b)
  # make sure all parse arguments are correct
  def assertParse(func):
    def decorator(*args, **kwargs):
      nonlocal func
      ASSERTEQ(set(kwargs.keys()), {'input','succ','fail','pmatch','inv'})
      DEBUG(*args, **kwargs)
      return func(*args, **kwargs)
    return decorator
  # make sure all succ arguments are correct
  def assertSucc(func):
    def decorator(*args, **kwargs):
      nonlocal func
      ASSERTEQ(set(kwargs.keys()), {'pmatch','input','fail'})
      return func(*args, **kwargs)
    return decorator
  # make sure all fail arguments are correct
  def assertFail(func):
    def decorator(*args, **kwargs):
      nonlocal func
      ASSERTEQ(set(kwargs.keys()), {'value','cont'})
      assert(kwargs['value'] != 0)
      return func(*args, **kwargs)
    return decorator
  # make sure all continuation arguments are correct
  def assertCont(func):
    def decorator(*args, **kwargs):
      nonlocal func
      ASSERTEQ(set(kwargs.keys()), {'fail'})
      return func(*args, **kwargs)
    return decorator
  
  def makeSucc(kwargs):
    def expand(succ=None,inv=None,**kwargs):
      return kwargs
    return expand(**kwargs)  
  
  global parse
  def parse(pobj, input, pmatch=None):
    nonlocal SUCC, FAIL
    assert(pobj.grammar is not None)
    parseArgs = {
      'input'     : fork(input),
      'succ'      : SUCC,
      'fail'      : FAIL,
      'pmatch'    : pmatch,
      'inv'       : None
    }
    result = tailEval(pobj.parse(**parseArgs))
    return result
  
  global Grammar
  class Grammar(object):
    def __init__(self):
      self.lookup   = {}
    def __setitem__(self, name, item):
      self.lookup[name] = item
      item.grammar = self
    def __getitem__(self, name):
      return Lookup(name=name,grammar=self)
  
  @assertSucc
  def SUCC(pmatch, input, **kwargs):
    return pmatch, input
  @assertFail
  def FAIL(value, cont, **kwargs):
    if value is None:
      return None
    else:
      return partial(cont,fail=FAIL)
  class ParseObject(object):
    def __init__(self, grammar=None, children=(), *args, **kwargs):
      super(ParseObject,self).__setattr__('grammar',None)
      self.children = tuple(children)
      for child in children: assert(child is not None)
      self.grammar  = grammar
      for child in children:
        self.grammar = child.grammar
      self.prec     = 0
    def __setattr__(self, name, value):
      update = False
      if name == "grammar":
        assert(value is None or issubclass(type(value), Grammar))
        update = value is not None and value != self.grammar
        # only update the grammar if the grammar is unassigned
        if update:
          assert(self.grammar is None)
      super(ParseObject,self).__setattr__(name, value)
      if update:
        for child in self.children: child.grammar = value
    def str(self, prec):
      return ("(?:%s)" if prec < self.prec else "%s") % str(self)
    def __or__(lhs, rhs):
      if lhs.alwaysFail(): return rhs
      if rhs.alwaysFail(): return lhs
      return Choice(children=[lhs,rhs])
    def __and__(lhs, rhs):
      return Sequence(children=[lhs,rhs])
    def __call__(self, op=None, **kwargs):
      if op is not None:
        kwargs['produce'] = op.produce
        kwargs['consume'] = op.consume
      return Match(self, **kwargs)
    def __lshift__(self, input):
      return parse(self, input)
    def __neg__(self):
      return Negative(self)
    def nomatch(self, pmatch, seen = set()):
      if self in seen: return pmatch
      seen = copy(seen)
      seen.add(self)
      for child in self.children:
        child.nomatch(pmatch, seen)
      return pmatch
    def alwaysSucc(self):
      return False
    def alwaysFail(self):
      return False
  DIE = lambda fail : partial(fail,value=None,cont=badcall)
  # a grammar lookup
  class Lookup(ParseObject):
    def __init__(self, name, *args, **kwargs):
      super(Lookup,self).__init__(*args, **kwargs)
      self.name = name
    def __str__(self):
      return("(?$%s)" % self.name)
    @assertParse
    def parse(self, **kwargs):
      return partial(self.grammar.lookup[self.name].parse, **kwargs)
    def __invert__(self):
      return self.grammar.lookup[self.name]
  # matches any value
  global Any
  class Any(ParseObject):
    def __init__(self, count = 1, *args, **kwargs):
      super(Any,self).__init__(*args,**kwargs)
      self.count = count
    def __str__(self):
      if self.count <= 0: return ""
      if self.count == 1: return "."
      return ".{%d}" % self.count
    @assertParse
    def parse(self, input, succ, fail, pmatch, **kwargs):
      match = tuple(next(input) for i in range(self.count))
      if len(match) < self.count:
        nonlocal DIE
        return DIE(fail)
      pmatch += match
      return partial(succ, input=input, pmatch=pmatch, fail=fail)
    def alwaysSucc(self):
      return self.count == 0
  global Charset
  class Charset(ParseObject):
    def __init__(self, set=(), *args, **kwargs):
      super(Charset,self).__init__(*args,**kwargs)
      self.set = set
    def __str__(self):
      return "[" + "".join(set) + "]"
    @assertParse
    def parse(self, input, succ, fail, pmatch, **kwargs):
      nonlocal DIE
      try:
        match = next(input)
        if match in self.set:
          pmatch += match,
          return partial(succ,input=input,pmatch=pmatch,fail=fail)
      except StopIteration:
        pass
      return DIE(fail)
  global Pattern
  class Pattern(ParseObject):
    def __init__(self, pattern=(), *args, **kwargs):
      super(Pattern,self).__init__(*args, **kwargs)
      self.pattern = pattern
    def __str__(self):
      return str(self.pattern)
    @assertParse
    def parse(self, input, succ, fail, pmatch, **kwargs):
      nonlocal DIE
      if not begins(self.pattern, input):
        return DIE(fail)
      pmatch += tuple(self.pattern)
      return partial(succ,input=input,pmatch=pmatch,fail=fail)
  # matches a value and saves it in the match object
  class Match(ParseObject):
    def __init__(self, sym, produce=None, consume=None, name=None, *args, **kwargs):
      super(Match,self).__init__(children=[sym], *args, **kwargs)
      self.sym  = sym
      self.produce = produce
      self.consume = consume
      self.name = name
    def __str__(self):
      if self.name:
        return "(%s)" % self.sym
      else:
        return "(?P<%s>%s)" % (self.name, self.sym)
    @assertParse
    def parse(self, input, succ, pmatch, **kwargs):
      if self.produce:
        pmatch  = self.produce(parent=pmatch, loc=input.loc(), name=self.name)
      #assertSucc
      def cleanup(pmatch, input, **skwargs):
        nonlocal self, succ
        if self.consume:
          pmatch = pmatch.consume(loc=input.loc(), name=self.name)
        return partial(succ, pmatch=pmatch, input=input, **skwargs)
      return partial(self.sym.parse,input=input,succ=cleanup,pmatch=pmatch,**kwargs)
    def nomatch(self, pmatch, seen=set()):
      if self not in seen:
        pmatch.nochild(self.name)
      if self.produce.capture:
        return super(Match,self).nomatch(pmatch=pmatch,seen=seen)
      else:
        return pmatch
  # fails to parse
  global Fail
  class Fail(ParseObject):
    def __init__(self, value=None, *args, **kwargs):
     super(Fail,self).__init__(*args,**kwargs)
     self.value = value
    def __str__(self):
      if self.value is None:
        return "(?~)"
      else:
        return "(?~%d)" % self.value
    @assertParse
    def parse(self, fail, succ, input, pmatch, **kwargs):
      @assertCont
      def cont(fail, **ckwargs):
        nonlocal succ,input,pmatch
        return partial(succ,fail=fail,input=input,pmatch=pmatch)
      return partial(fail,value=self.value,cont=cont)
    def alwaysFail(self):
      return True
  # a sequence of symbls
  class Sequence(ParseObject):
    def __init__(self, children, *args, **kwargs):
      super(Sequence,self).__init__(children=children,*args,**kwargs)
      self.prec = 1
    def __str__(self):
      return "".join(p.str(self.prec) for p in self.children)
    @assertParse
    def parse(self, input, succ, pmatch, **kwargs):
      acc = succ
      for p in reversed(self.children):
        def bind(p, acc):
          @assertSucc
          def succ(input, pmatch, **skwargs):
            nonlocal kwargs, p, acc
            return partial(p.parse,input=input,succ=acc,pmatch=pmatch,**kwargs)
          return succ
        acc = bind(p, acc)
      return partial(acc,input=input,pmatch=pmatch,**makeSucc(kwargs))
    def alwaysSucc(self):
      return all(child.alwaysSucc() for child in self.children)
    def alwaysFail(self):
      return any(child.alwaysFail() for child in self.children)
  # and ordered choice
  class Choice(ParseObject):
    def __init__(self, *args, **kwargs):
      super(Choice,self).__init__(*args,**kwargs)
      self.prec = 2
    def __str__(self):
      return "|".join(p.str(self.prec) for p in self.children)
    @assertParse
    def parse(self, input, fail, pmatch, succ, **kwargs):
      inputs = input.fork(len(self.children))
      queue  = PriorityQueue(len(self.children))
      def bind(choice):
        @assertSucc
        def cleanup(pmatch, **skwargs):
          nonlocal choice, succ
          for child in self.children[choice+1:]:
            pmatch = child.nomatch(pmatch)
          return partial(succ,pmatch=pmatch,**skwargs)
        @assertSucc
        def succ2(pmatch, **skwargs):
          nonlocal self, choice, kwargs
          func = partial(self.children[choice].parse, **kwargs)
          for child in self.children[:choice]:
            pmatch = child.nomatch(pmatch)
          return partial(func,pmatch=pmatch,succ=cleanup,**skwargs)
        return succ2
      for i, (input,child) in enumerate(zip(inputs,self.children)):
        queue.put((0,i,partial(bind(i),input=input,pmatch=copy(pmatch))))
      current = queue.get()
      @assertCont
      def cont2(fail, **kwargs):
        nonlocal current
        assert(current is not None)
        return partial(current[2],fail=fail2)
      @assertFail
      def fail2(value,cont,**kwargs):
        nonlocal fail, queue, current, DIE
        last = current[0]
        if value is not None:
          queue.put((last+value,current[1],cont))
        if not queue.qsize():
          return partial(fail,value=None,cont=DIE)
        current = queue.get()
        if current[0] == last:
          return partial(current[2],fail=fail2)
        return partial(fail,value=last-current[0],cont=cont2)
      return partial(current[2],fail=fail2)
    def alwaysFail(self):
      return all(child.alwaysFail() for child in self.children)
  class Negative(ParseObject):
    def __init__(self, sym, *args, **kwargs):
      super(Negative,self).__init__(children=(sym,),*args,**kwargs)
    def __str__(self):
      return "(?!" + str(self.children[0]) + ")"
    @assertParse
    def parse(self, input, fail, pmatch, succ, **kwargs):
      input2 = input.fork()
      def succ2(**skwargs):
        nonlocal fail
        return partial(fail,value=None,cont=DIE)
      def fail2(**fkwargs):
        nonlocal succ, input2, kwargs, makeSucc
        return partial(succ,input=input2,pmatch=pmatch,fail=fail,**makeSucc(kwargs))
      return partial(self.children[0].parse,input=input,pmatch=copy(pmatch),fail=fail2,succ=succ2,**kwargs)
    def alwaysSucc(self):
      return self.children[0].alwaysFail()
    def alwaysFail(self):
      return self.children[0].alwaysSucc()
  global BasicMatch
  class BasicMatch(object):
    def __init__(self, parent=None, consume=identity, iadd=None, result=None, capture=True, *args, **kwargs):
      self.parent = parent
      self.result = copy(result)
      self._consume = consume
      self._iadd = iadd
      self.capture = capture
    def __iadd__(self, rhs):
      if self._iadd:
        self.result = self._iadd(self.result, rhs)
      return self
    def produce(self, parent=None, **kwargs):
      return type(self)(parent=parent,consume=self._consume,iadd=self._iadd,result=self.result)
    def consume(self, **kwargs):
      if self.parent and self._consume:
        self.parent += self._consume(self.result)
      return self.parent
      
private()
