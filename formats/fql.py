#---------------------------------------------------------------
# PyNLPl - FoLiA Query Language
#   by Maarten van Gompel
#   Centre for Language Studies
#   Radboud University Nijmegen
#   http://proycon.github.com/folia
#   http://www.github.com/proycon/pynlpl
#   proycon AT anaproy DOT nl
#
#   Module for reading, editing and writing FoLiA XML using
#   the FoLiA Query Language
#
#   Licensed under GPLv3
#
#----------------------------------------------------------------

from pynlpl.formats import folia
from copy import copy
import json
import re
import sys

OPERATORS = ('=','==','!=','>','<','<=','>=')
MASK_NORMAL = 0
MASK_LITERAL = 1
MASK_EXPRESSION = 2


class SyntaxError(Exception):
    pass

class QueryError(Exception):
    pass

class UnparsedQuery(object):
    """This class takes care of handling grouped blocks in parentheses and handling quoted values"""
    def __init__(self, s, i=0):
        self.q = []
        self.mask = []
        l = len(s)
        begin = 0
        while i < l:
            c = s[i]
            if c == " ":
                #process previous word
                if begin < i:
                    self.q.append(s[begin:i])
                    self.mask.append(MASK_NORMAL)
                begin = i + 1
            elif i == l - 1:
                #process last word
                self.q.append(s[begin:])
                self.mask.append(MASK_NORMAL)

            if c == '(': #groups
                #find end quote and process block
                level = 0
                quoted = False
                s2 = ""
                for j in range(i+1,l):
                    c2 = s[j]
                    if c2 == '"':
                        if s[j-1] != "\\": #check it isn't escaped
                            quoted = not quoted
                    if not quoted:
                        if c2 == '(':
                            level += 1
                        elif c2 == ')':
                            if level == 0:
                                s2 = s[i+1:j]
                                break
                            else:
                                level -= 1
                if s2:
                    self.q.append(UnparsedQuery(s2))
                    self.mask.append(MASK_EXPRESSION)
                    i = j
                    begin = i+1
                else:
                    raise SyntaxError("Unmatched parenthesis at char " + str(i))
            elif c == '"': #literals
                if i == 0 or (i > 0 and s[i-1] != "\\"): #check it isn't escaped
                    #find end quote and process block
                    s2 = None
                    for j in range(i+1,l):
                        c2 = s[j]
                        if c2 == '"':
                            if s[j-1] != "\\": #check it isn't escaped
                                s2 = s[i+1:j]
                                break
                    if not s2 is None:
                        self.q.append(s2)
                        self.mask.append(MASK_LITERAL)
                        i = j
                        begin = i+1
                    else:
                        raise SyntaxError("Unterminated string literal at char " + str(i))

            i += 1


    def __iter__(self):
        for w in self.q:
            yield w

    def __len__(self):
        return len(self.q)

    def __getitem__(self, index):
        try:
            return self.q[index]
        except KeyError:
            return ""

    def kw(self, index, value):
        if isinstance(value, tuple):
            return self.q[index] in value and self.mask[index] == MASK_NORMAL
        else:
            return self.q[index] == value and self.mask[index] == MASK_NORMAL


    def __exists__(self, keyword):
        for k,m in zip(self.q,self.mask):
            if keyword == k and m == MASK_NORMAL:
                return True
        return False

    def __setitem__(self, index, value):
        self.q[index] = value


    def __str__(self):
        s = []
        for w,m in zip(self.q,self.mask):
            if m == MASK_NORMAL:
                s.append(w)
            elif m == MASK_LITERAL:
                s.append('"' + w + '"')
            elif m == MASK_EXPRESSION:
                s.append('(' + str(w) + ')')
        return " ".join(s)






class Filter(object): #WHERE ....
    def __init__(self, filters, negation=False,disjunction=False,subfilters=[]):
        self.filters = filters
        self.negation = negation
        self.disjunction = disjunction
        self.subfilters = subfilters

    @staticmethod
    def parse(q, i=0):
        filters = []
        subfilters = []
        negation = False
        logop = ""

        l = len(q)
        while i < l:
            if q.kw(i, "NOT"):
                negation = True
                i += 1
            elif q[i+1] in OPERATORS and q[i] and q[i+2]:
                operator = q[i+1]
                if q[i] == "class":
                    v = lambda x,y='cls': getattr(x,y)
                elif q[i] == "text":
                    v = lambda x,y='text': getattr(x,'text')()
                else:
                    v = lambda x,y=q[i]: getattr(x,y)
                if operator == '=' or operator == '==':
                    filters.append( lambda x,y=q[i+2],v=v : v(x) == y )
                elif operator == '!=':
                    filters.append( lambda x,y=q[i+2],v=v : v(x) != y )
                elif operator == '>':
                    filters.append( lambda x,y=q[i+2],v=v : v(x) > y )
                elif operator == '<':
                    filters.append( lambda x,y=q[i+2],v=v : v(x) < y )
                elif operator == '>=':
                    filters.append( lambda x,y=q[i+2],v=v : v(x) >= y )
                elif operator == '<=':
                    filters.append( lambda x,y=q[i+2],v=v : v(x) <= y )
                elif operator == 'CONTAINS':
                    filters.append( lambda x,y=q[i+2],v=v : v(x).find( y ) != -1 )
                elif operator == 'MATCHES':
                    filters.append( lambda x,y=re.compile(q[i+2]),v=v : y.search(v(x)) is not None  )

                if q.kw(i+3,("AND","OR")):
                    if logop and q[i+3] != logop:
                        raise SyntaxError("Mixed logical operators, use parentheses: " + str(q))
                    logop = q[i+3]
                    i += 4
                else:
                    i += 3
                    break #done
            elif 'HAS' in q:
                #has statement (spans full UnparsedQuery by definition)
                #check for modifiers
                modifier = None
                if q[i].startswith("PREVIOUS") or q[i].startswith("NEXT") or  q.kw(i, ("LEFTCONTEXT","RIGHTCONTEXT","CONTEXT","PARENT","ANCESTOR") ):
                    modifier = q[i]
                    i += 1

                selector,i =  Selector.parse(q,i)
                if q[i] != "HAS":
                    raise SyntaxError("Expected HAS, got " + q[i] + " in: " + str(q))
                i += 1
                subfilter = Filter.parse(q,i)
                filters.append( (selector,subfilter) )
            elif isinstance(q[i], UnparsedQuery):
                filter,_  = Filter.parse(q[i])
                filters.append(filter)
                i += 1
                if q.kw(i,"AND") or q.kw(i, "OR"):
                    if logop and q[i] != logop:
                        raise SyntaxError("Mixed logical operators, use parentheses: " + str(q))
                    logop = q[i]
                else:
                    break #done
            else:
                raise SyntaxError("Expected comparison operator, got " + q[i+1] + " in: " + str(q))

        if negation and len(filters) > 1:
            raise SyntaxError("Expecting parentheses when NOT is used with multiple conditions")

        return Filter(filters, negation, logop == "OR",subfilters), i

    def __call__(self, query, element, debug=False):
        """Tests the filter on the specified element, returns a boolean"""
        match = True
        if debug: print("[FQL EVALUATION DEBUG] Filter - Applying filter for ", element,file=sys.stderr)
        for filter in self.filters:
            if isinstance(filter,tuple):
                if debug: print("[FQL EVALUATION DEBUG] Filter - Filter is a subfilter, descending...",file=sys.stderr)
                #we have a subfilter, i.e. a HAS statement on a subelement
                selector, filter = filter
                for subelement in selector(query, [element], debug): #if there are multiple subelements, they are always treated disjunctly
                    match = subfilter(query, subelement, debug)
                    if match:
                        break #only one subelement has to match by definition, then the HAS statement is matched
            elif isinstance(filter, Filter):
                #we have a nested filter (parentheses)
                match = filter(query, element, debug)
            else:
                #we have a condition function we can evaluate
                match = filter(element)
            if self.negation:
                match = not match
            if match:
                if self.disjunction:
                    return True
            else:
                if not self.disjunction: #implies conjunction
                    return False

        return match




class Selector(object):
    def __init__(self, Class, set=None,id=None, filter=None):
        self.Class = Class
        self.set = set
        self.id = id
        self.filter = filter

    @staticmethod
    def parse(q, i=0):
        l = len(q)
        set = None
        id = None
        filter = None

        if q[i] == "ID" and q[i+1]:
            id = q[i+1]
            Class = None
            i += 2
        else:
            try:
                Class = folia.XML2CLASS[q[i]]
            except:
                raise SyntaxError("Expected element type, got " + q[i] + " in: " + str(q))
            i += 1

        while i < l:
            if q.kw(i,"OF") and q[i+1]:
                set = q[i+1]
                i += 2
            elif q.kw(i,"ID") and q[i+1]:
                id = q[i+1]
                i += 2
            elif q.kw(i, "WHERE"):
                #ok, big filter coming up!
                filter, i = Filter.parse(q,i+1)
                break
            else:
                #something we don't handle
                break

        return Selector(Class,set,id,filter), i

    def __call__(self, query, selection, recurse=True, debug=False): #generator, lazy evaluation!
        if self.id:
            if debug: print("[FQL EVALUATION DEBUG] Selector - Selecting ID " + self.id,file=sys.stderr)
            try:
                candidate = query.doc[self.id]
                if not self.filter or  self.filter(query,candidate):
                    yield candidate
            except KeyError:
                pass
        elif self.Class:
            if self.Class.XMLTAG in query.defaultsets:
                self.set = query.defaultsets
            if debug: print("[FQL EVALUATION DEBUG] Selector -  Selecting ID " + self.Class.XMLTAG + " with set " + str(self.set),file=sys.stderr)
            for e in selection:
                for candidate in e.select(self.Class, self.set, recurse):
                    if not self.filter or  self.filter(query,candidate):
                        if debug: print("[FQL EVALUATION DEBUG] Selector - Yielding candidate ", candidate,file=sys.stderr)
                        yield candidate


class Span(object):
    pass #TODO

class Target(object): #FOR/IN... expression
    def __init__(self, targets, strict=False,nested = None):
        self.targets = targets #Selector instances
        self.strict = strict #True for IN
        self.nested = nested #in a nested another target

    @staticmethod
    def parse(q, i=0):
        if q.kw(i,'FOR'):
            strict = False
        elif q.kw(i,'IN'):
            strict = True
        else:
            raise SyntaxError("Expected target expression, got " + q[i] + " in: " + str(q))
        i += 1

        targets = []
        nested = None
        l = len(q)
        while i < l:
            if q.kw(i,'SPAN'):
                raise NotImplementedError #TODO
            elif q.kw(i,"ID") or q[i] in folia.XML2CLASS:
                target,i = Selector.parse(q,i)
                targets.append(target)
            elif q.kw(i,","):
                #we're gonna have more targets
                i += 1
            elif q.kw(i, ('FOR','IN')):
                nested,i = Selector.parse(q,i)
            else:
                break

        if not targets:
            raise SyntaxError("Expected one or more targets, got " + q[i] + " in: " + str(q))

        return Target(targets,strict,nested), i


    def __call__(self, query, selection, debug=False): #generator, lazy evaluation!
        if self.nested:
            if debug: print("[FQL EVALUATION DEBUG] Target - Deferring to nested target first",file=sys.stderr)
            selection = self.nested(query, selection)


        if debug: print("[FQL EVALUATION DEBUG] Target - Calling target selectors",file=sys.stderr)
        if len(self.targets) > 1: selection = list(selection) #multiple targets specified, one-pass won't do so convert generator to list
        for target in self.targets:
            for e in target(query, selection, not self.strict, debug):
                if debug: print("[FQL EVALUATION DEBUG] Target - Yielding  ",e, file=sys.stderr)
                yield e


class Form(object):  #AS... expression
    pass #TODO


class Action(object): #Action expression
    def __init__(self, action, actor, assignments={}):
        self.action = action
        self.actor = actor
        self.assignments = assignments
        self.form = None
        self.subactions = []
        self.nextaction = None
        self.respan = []


    @staticmethod
    def parse(q,i=0):
        if q.kw(i, ('SELECT','EDIT','DELETE','ADD','APPEND','PREPEND','MERGE','SPLIT')):
            action = q[i]
        else:
            raise SyntaxError("Expected action, got " + q[i] + " in: " + str(q))

        i += 1
        actor, i = Selector.parse(q,i)

        if action == "ADD" and actor.filter:
            raise SyntaxError("Actor has WHERE statement but ADD action does not support this")

        assignments = {}
        if q.kw(i,"WITH"):
            if action in ("SELECT", "DELETE"):
                raise SyntaxError("Actor has WITH statement but " + action + " does not support this: " +str(q))
            i += 1
            l = len(q)
            while i < l:
                if q.kw(i, ('annotator','annotatortype','class','confidence','n','text')):
                    assignments[q[i]] = q[i+1]
                    i+=1
                else:
                    if not assignments:
                        raise SyntaxError("Expected assignments after WITH statement, but no valid attribute found: " + str(q))
                    break
            i+=1

        #we have enough to set up the action now
        action = Action(action, actor, assignments)

        if action.action == "EDIT" and q.kw(i,"SPAN"):
            raise NotImplementedError #TODO

        done = False
        while not done:
            if isinstance(q[i], UnparsedQuery):
                #we have a sub expression
                if q.kw(i, ('EDIT','DELETE','ADD')):
                    #It's a sub-action!
                    subaction, _ = Action.parse(q[i])
                    action.subactions.append( subaction )
                elif q.kw(i, 'AS'):
                    #It's an AS.. expression
                    #self.form = #TODO
                    raise NotImplementedError #TODO
                i+=1
            else:
                done = True

        if q.kw(i, ('SELECT','EDIT','DELETE','ADD','APPEND','PREPEND','MERGE','SPLIT')):
            #We have another action!
            action.nextaction, i = Action.parse(q,i)

        return action, i


    def __call__(self, query, targetselection, debug=False):
        """Returns a list actorselection after having performed the desired action on each element therein"""

        if debug: print("[FQL EVALUATION DEBUG] Action - Evaluation action ", self.action,file=sys.stderr)
        #select all actors, not lazy because we are going return them all by definition anyway
        actorselection = []
        for e in self.actor(query, targetselection):
            if debug: print("[FQL EVALUATION DEBUG] Action - Got actor result, appending ", repr(e),file=sys.stderr)
            actorselection.append(e)

        if self.action == "EDIT" or self.action == "ADD":
            raise NotImplementedError #TODO
        elif self.action == "PREPEND":
            raise NotImplementedError #TODO
        elif self.action == "APPEND":
            raise NotImplementedError #TODO
        elif self.action == "MERGE":
            raise NotImplementedError #TODO
        elif self.action == "SPLIT":
            raise NotImplementedError #TODO
        elif self.action == "SELECT":
            #nothing to do
            pass

        return actorselection



class Context(object):
    def __init__(self):
        self.format = "python"
        self.returntype = "actor"
        self.request = "all"
        self.defaults = {}
        self.defaultsets = {}

class Query(object):
    def __init__(self, q, context=Context()):
        self.action = None
        self.targets = None
        self.format = context.format
        self.returntype = context.returntype
        self.request = copy(context.request)
        self.defaults = copy(context.defaults)
        self.defaultsets = copy(context.defaultsets)
        self.parse(q)

    def parse(self, q, i=0):
        if not isinstance(q,UnparsedQuery):
            q = UnparsedQuery(q)

        l = len(q)
        self.action,i = Action.parse(q,i)

        if q.kw(i,("FOR","IN")):
            self.targets, i = Target.parse(q,i)

        while i < l:
            if q.kw(i,"RETURN"):
                self.returntype = q[i+1]
                i+=2
            elif q.kw(i,"FORMAT"):
                self.format = q[i+1]
                i+=2
            elif q.kw(i,"REQUEST"):
                self.request = q[i+1].split(",")
                i+=2
            else:
                raise SyntaxError("Unexpected " + q[i] + " at position " + str(i) + " in: " + str(q))


        if i != l:
            raise SyntaxError("Expected end of query, got " + q[i] + " in: " + str(q))

    def __call__(self, doc, debug=False):
        """Execute the query on the specified document"""

        self.doc = doc

        if debug: print("[FQL EVALUATION DEBUG] Query - Starting on document ", doc.id,file=sys.stderr)

        targetselection = [ doc.data[0] ]
        if self.targets:
            targetselection = self.targets(self, targetselection, debug)


        if self.returntype == "target" or self.returntype == "inner-target" or self.returntype == "outer-target":
            targetselection = list(targetselection) #we need all in memory

        actorselection = self.action(self, targetselection, debug)

        if self.returntype == "actor":
            responseselection = list(actorselection)
        elif self.returntype == "target" or self.returntype == "inner-target":
            responseselection = list(targetselection)
        elif self.returntype == "outer-target":
            raise NotImplementedError
        elif self.returntype == "ancestor-target":
            raise NotImplementedError
        else:
            return QueryError("Invalid return type: " + self.returntype)


        #convert response selection to proper format and return
        if self.format.startswith('single'):
            if len(responseselection) > 1:
                raise QueryError("A single response was expected, but multiple are returned")
            if self.format == "single-xml":
                if debug: print("[FQL EVALUATION DEBUG] Query - Returning single-xml",file=sys.stderr)
                if not responseselection:
                    return ""
                else:
                    return responseselection[0].xmlstring(True)
            elif self.format == "single-json":
                if debug: print("[FQL EVALUATION DEBUG] Query - Returning single-json",file=sys.stderr)
                if not responseselection:
                    return "null"
                else:
                    return json.dumps(responseselection[0].json())
            elif self.format == "single-python":
                if debug: print("[FQL EVALUATION DEBUG] Query - Returning single-python",file=sys.stderr)
                if not responseselection:
                    return None
                else:
                    return responseselection[0]
        else:
            if self.format == "xml":
                if debug: print("[FQL EVALUATION DEBUG] Query - Returning xml",file=sys.stderr)
                if not responseselection:
                    return "<results></results>"
                else:
                    r = "<results>\n"
                    for e in responseselection:
                        r += "<result>\n" + e.xmlstring(True) + "\n</result>\n"
                    r += "</results>\n"
                    return r
            elif self.format == "json":
                if debug: print("[FQL EVALUATION DEBUG] Query - Returning json",file=sys.stderr)
                if not responseselection:
                    return "[]"
                else:
                    return json.dumps([ e.json() for e in responseselection ] )
            elif self.format == "python":
                if debug: print("[FQL EVALUATION DEBUG] Query - Returning python",file=sys.stderr)
                return responseselection

        return QueryError("Invalid format: " + self.format)









