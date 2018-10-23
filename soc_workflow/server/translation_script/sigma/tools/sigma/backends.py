# Output backends for sigmac
# Copyright 2016-2017 Thomas Patzke, Florian Roth, Ben de Haan, Devin Ferguson

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys
import json
import re
import sigma

def getBackendList():
    """Return list of backend classes"""
    return list(filter(lambda cls: type(cls) == type and issubclass(cls, BaseBackend) and cls.active, [item[1] for item in globals().items()]))

def getBackendDict():
    return {cls.identifier: cls for cls in getBackendList() }

def getBackend(name):
    try:
        return getBackendDict()[name]
    except KeyError as e:
        raise LookupError("Backend not found") from e

class BackendOptions(dict):
    """Object contains all options that should be passed to the backend from command line (or other user interfaces)"""

    def __init__(self, options):
        """
        Receives the argparser result from the backend option paramater value list (nargs=*) and builds the dict from it. There are two option types:

        * key=value: self{key} = value
        * key: self{key} = True
        """
        if options == None:
            return
        for option in options:
            parsed = option.split("=", 1)
            try:
                self[parsed[0]] = parsed[1]
            except IndexError:
                self[parsed[0]] = True

### Output classes
class SingleOutput:
    """
    Single file output

    By default, this opens the given file or stdin and passes everything into this.
    """
    def __init__(self, filename=None):
        if type(filename) == str:
            self.fd = open(filename, "w", encoding='utf-8')
        else:
            self.fd = sys.stdout

    def print(self, *args, **kwargs):
        print(*args, file=self.fd, **kwargs)

    def close(self):
        self.fd.close()

### Generic backend base classes and mixins
class BaseBackend:
    """Base class for all backends"""
    identifier = "base"
    active = False
    index_field = None    # field name that is used to address indices
    output_class = None   # one of the above output classes
    file_list = None

    def __init__(self, sigmaconfig, backend_options=None, filename=None):
        """
        Initialize backend. This gets a sigmaconfig object, which is notified about the used backend class by
        passing the object instance to it. Further, output files are initialized by the output class defined in output_class.
        """
        super().__init__()
        if not isinstance(sigmaconfig, (sigma.config.SigmaConfiguration, None)):
            raise TypeError("SigmaConfiguration object expected")
        self.options = backend_options
        self.sigmaconfig = sigmaconfig
        self.sigmaconfig.set_backend(self)
        self.output = self.output_class(filename)

    def generate(self, sigmaparser):
        """Method is called for each sigma rule and receives the parsed rule (SigmaParser)"""
        for parsed in sigmaparser.condparsed:
            self.output.print(self.generateQuery(parsed))

    def generateQuery(self, parsed):
        result = self.generateNode(parsed.parsedSearch)
        if parsed.parsedAgg:
            result += self.generateAggregation(parsed.parsedAgg)
        return result

    def generateNode(self, node):
        if type(node) == sigma.parser.ConditionAND:
            return self.generateANDNode(node)
        elif type(node) == sigma.parser.ConditionOR:
            return self.generateORNode(node)
        elif type(node) == sigma.parser.ConditionNOT:
            return self.generateNOTNode(node)
        elif type(node) == sigma.parser.ConditionNULLValue:
            return self.generateNULLValueNode(node)
        elif type(node) == sigma.parser.ConditionNotNULLValue:
            return self.generateNotNULLValueNode(node)
        elif type(node) == sigma.parser.NodeSubexpression:
            return self.generateSubexpressionNode(node)
        elif type(node) == tuple:
            return self.generateMapItemNode(node)
        elif type(node) in (str, int):
            return self.generateValueNode(node)
        elif type(node) == list:
            return self.generateListNode(node)
        else:
            raise TypeError("Node type %s was not expected in Sigma parse tree" % (str(type(node))))

    def generateANDNode(self, node):
        raise NotImplementedError("Node type not implemented for this backend")

    def generateORNode(self, node):
        raise NotImplementedError("Node type not implemented for this backend")

    def generateNOTNode(self, node):
        raise NotImplementedError("Node type not implemented for this backend")

    def generateSubexpressionNode(self, node):
        raise NotImplementedError("Node type not implemented for this backend")

    def generateListNode(self, node):
        raise NotImplementedError("Node type not implemented for this backend")

    def generateMapItemNode(self, node):
        raise NotImplementedError("Node type not implemented for this backend")

    def generateValueNode(self, node):
        raise NotImplementedError("Node type not implemented for this backend")

    def generateNULLValueNode(self, node):
        raise NotImplementedError("Node type not implemented for this backend")

    def generateNotNULLValueNode(self, node):
        raise NotImplementedError("Node type not implemented for this backend")

    def generateAggregation(self, agg):
        raise NotImplementedError("Aggregations not implemented for this backend")

    def finalize(self):
        """
        Is called after the last file was processed with generate(). The right place if this backend is not intended to
        look isolated at each rule, but generates an output which incorporates multiple rules, e.g. dashboards.
        """
        pass

class QuoteCharMixin:
    """
    This class adds the cleanValue method that quotes and filters characters according to the configuration in
    the attributes provided by the mixin.
    """
    reEscape = None                     # match characters that must be quoted
    escapeSubst = "\\\\\g<1>"           # Substitution that is applied to characters/strings matched for escaping by reEscape
    reClear = None                      # match characters that are cleaned out completely

    def cleanValue(self, val):
        if self.reEscape:
            val = self.reEscape.sub(self.escapeSubst, val)
        if self.reClear:
            val = self.reClear.sub("", val)
        return val

class SingleTextQueryBackend(BaseBackend, QuoteCharMixin):
    """Base class for backends that generate one text-based expression from a Sigma rule"""
    identifier = "base-textquery"
    active = False
    output_class = SingleOutput

    # the following class variables define the generation and behavior of queries from a parse tree some are prefilled with default values that are quite usual
    andToken = None                     # Token used for linking expressions with logical AND
    orToken = None                      # Same for OR
    notToken = None                     # Same for NOT
    subExpression = None                # Syntax for subexpressions, usually parenthesis around it. %s is inner expression
    listExpression = None               # Syntax for lists, %s are list items separated with listSeparator
    listSeparator = None                # Character for separation of list items
    valueExpression = None              # Expression of values, %s represents value
    nullExpression = None               # Expression of queries for null values or non-existing fields. %s is field name
    notNullExpression = None            # Expression of queries for not null values. %s is field name
    mapExpression = None                # Syntax for field/value conditions. First %s is key, second is value
    mapListsSpecialHandling = False     # Same handling for map items with list values as for normal values (strings, integers) if True, generateMapItemListNode method is called with node
    mapListValueExpression = None       # Syntax for field/value condititons where map value is a list

    def generateANDNode(self, node):
        return self.andToken.join([self.generateNode(val) for val in node])

    def generateORNode(self, node):
        return self.orToken.join([self.generateNode(val) for val in node])

    def generateNOTNode(self, node):
        return self.notToken + self.generateNode(node.item)

    def generateSubexpressionNode(self, node):
        return self.subExpression % self.generateNode(node.items)

    def generateListNode(self, node):
        if not set([type(value) for value in node]).issubset({str, int}):
            raise TypeError("List values must be strings or numbers")
        return self.listExpression % (self.listSeparator.join([self.generateNode(value) for value in node]))

    def generateMapItemNode(self, node):
        key, value = node
        if self.mapListsSpecialHandling == False and type(value) in (str, int, list) or self.mapListsSpecialHandling == True and type(value) in (str, int):
            return self.mapExpression % (key, self.generateNode(value))
        elif type(value) == list:
            return self.generateMapItemListNode(key, value)
        else:
            raise TypeError("Backend does not support map values of type " + str(type(value)))

    def generateMapItemListNode(self, key, value):
        return self.mapListValueExpression % (key, self.generateNode(value))

    def generateValueNode(self, node):
        return self.valueExpression % (self.cleanValue(str(node)))

    def generateNULLValueNode(self, node):
        return self.nullExpression % (node.item)

    def generateNotNULLValueNode(self, node):
        return self.notNullExpression % (node.item)

class MultiRuleOutputMixin:
    """Mixin with common for multi-rule outputs"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rulenames = set()

    def getRuleName(self, sigmaparser):
        """
        Generate a rule name from the title of the Sigma rule with following properties:

        * Spaces are replaced with -
        * Unique name by addition of a counter if generated name already in usage

        Generated names are tracked by the Mixin.
        
        """
        rulename = sigmaparser.parsedyaml["title"].replace(" ", "-")
        if rulename in self.rulenames:   # add counter if name collides
            cnt = 2
            while "%s-%d" % (rulename, cnt) in self.rulenames:
                cnt += 1
            rulename = "%s-%d" % (rulename, cnt)
        self.rulenames.add(rulename)

        return rulename

### Backends for specific SIEMs

class ElasticsearchQuerystringBackend(SingleTextQueryBackend):
    """Converts Sigma rule into Elasticsearch query string. Only searches, no aggregations."""
    identifier = "es-qs"
    active = True

    reEscape = re.compile("([+\\-=!(){}\\[\\]^\"~:\\\\/]|&&|\\|\\|)")
    reClear = re.compile("[<>]")
    andToken = " AND "
    orToken = " OR "
    notToken = "NOT "
    subExpression = "(%s)"
    listExpression = "(%s)"
    listSeparator = " "
    valueExpression = "\"%s\""
    nullExpression = "NOT _exists_:%s"
    notNullExpression = "_exists_:%s"
    mapExpression = "%s:%s"
    mapListsSpecialHandling = False

class KibanaBackend(ElasticsearchQuerystringBackend, MultiRuleOutputMixin):
    """Converts Sigma rule into Kibana JSON Configuration files (searches only)."""
    identifier = "kibana"
    active = True
    output_class = SingleOutput

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.kibanaconf = list()

    def generate(self, sigmaparser):
        rulename = self.getRuleName(sigmaparser)
        description = sigmaparser.parsedyaml.setdefault("description", "")

        columns = list()
        try:
            for field in sigmaparser.parsedyaml["fields"]:
                mapped = sigmaparser.config.get_fieldmapping(field).resolve_fieldname(field)
                if type(mapped) == str:
                    columns.append(mapped)
                elif type(mapped) == list:
                    columns.extend(mapped)
                else:
                    raise TypeError("Field mapping must return string or list")
        except KeyError:    # no 'fields' attribute
            pass

        indices = sigmaparser.get_logsource().index
        if len(indices) == 0:   # fallback if no index is given
            indices = ["*"]

        for parsed in sigmaparser.condparsed:
            result = self.generateNode(parsed.parsedSearch)

            for index in indices:
                final_rulename = rulename
                if len(indices) > 1:     # add index names if rule must be replicated because of ambigiuous index patterns
                    raise NotSupportedError("Multiple target indices are not supported by Kibana")
                else:
                    title = sigmaparser.parsedyaml["title"]
                try:
                    title = self.options["prefix"] + title
                except KeyError:
                    pass

                self.kibanaconf.append({
                        "_id": final_rulename,
                        "_type": "search",
                        "_source": {
                            "title": title,
                            "description": description,
                            "hits": 0,
                            "columns": columns,
                            "sort": ["@timestamp", "desc"],
                            "version": 1,
                            "kibanaSavedObjectMeta": {
                                "searchSourceJSON": json.dumps({
                                    "index": index,
                                    "filter":  [],
                                    "highlight": {
                                        "pre_tags": ["@kibana-highlighted-field@"],
                                        "post_tags": ["@/kibana-highlighted-field@"],
                                        "fields": { "*":{} },
                                        "require_field_match": False,
                                        "fragment_size": 2147483647
                                        },
                                    "query": {
                                        "query_string": {
                                            "query": result,
                                            "analyze_wildcard": True
                                            }
                                        }
                                    }
                                )
                            }
                        }
                    })

    def finalize(self):
        self.output.print(json.dumps(self.kibanaconf, indent=2))

class XPackWatcherBackend(ElasticsearchQuerystringBackend, MultiRuleOutputMixin):
    """Converts Sigma Rule into X-Pack Watcher JSON for alerting"""
    identifier = "xpack-watcher"
    active = True
    output_class = SingleOutput

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.watcher_alert = dict()
        try:
            self.output_type = self.options["output"]
        except KeyError:
            self.output_type = "curl"

        try:
            self.es = self.options["es"]
        except KeyError:
            self.es = "localhost:9200"

    def generate(self, sigmaparser):
        # get the details if this alert occurs
        rulename = self.getRuleName(sigmaparser)
        description = sigmaparser.parsedyaml.setdefault("description", "")
        false_positives = sigmaparser.parsedyaml.setdefault("falsepositives", "")
        level = sigmaparser.parsedyaml.setdefault("level", "")
        logging_result = "Rule description: "+str(description)+", false positives: "+str(false_positives)+", level: "+level
        # Get time frame if exists
        interval = sigmaparser.parsedyaml["detection"].setdefault("timeframe", "30m")

        # creating condition
        indices = sigmaparser.get_logsource().index

        for condition in sigmaparser.condparsed:
            result = self.generateNode(condition.parsedSearch)
            try:
                if condition.parsedAgg.cond_op == ">":
                    alert_condition = { "gt": int(condition.parsedAgg.condition) }
                elif condition.parsedAgg.cond_op == ">=":
                    alert_condition = { "gte": int(condition.parsedAgg.condition) }
                elif condition.parsedAgg.cond_op == "<":
                    alert_condition = { "lt": int(condition.parsedAgg.condition) }
                elif condition.parsedAgg.cond_op == "<=":
                    alert_condition = { "lte": int(condition.parsedAgg.condition) }
                else:
                    alert_condition = {"not_eq": 0}
            except KeyError:
                alert_condition = {"not_eq": 0}
            except AttributeError:
                alert_condition = {"not_eq": 0}

            self.watcher_alert[rulename] = {
                              "trigger": {
                                "schedule": {
                                  "interval": interval  # how often the watcher should check
                                }
                              },
                              "input": {
                                "search": {
                                  "request": {
                                    "body": {
                                      "size": 0,
                                      "query": {
                                        "query_string": {
                                            "query": result,  # this is where the elasticsearch query syntax goes
                                            "analyze_wildcard": True
                                        }
                                      }
                                    },
                                    "indices": indices
                                  }
                                }
                              },
                              "condition": {
                                  "compare": {    # TODO: Issue #49
                                  "ctx.payload.hits.total": alert_condition
                                }
                              },
                              "actions": {
                                "logging-action": {
                                  "logging": {
                                    "text": logging_result
                                  }
                                }
                              }
                            }

    def finalize(self):
        for rulename, rule in self.watcher_alert.items():
            if self.output_type == "plain":     # output request line + body
                self.output.print("PUT _xpack/watcher/watch/%s\n%s\n" % (rulename, json.dumps(rule, indent=2)))
            elif self.output_type == "curl":      # output curl command line
                self.output.print("curl -s -XPUT --data-binary @- %s/_xpack/watcher/watch/%s <<EOF\n%s\nEOF" % (self.es, rulename, json.dumps(rule, indent=2)))
            else:
                raise NotImplementedError("Output type '%s' not supported" % self.output_type)

class LogPointBackend(SingleTextQueryBackend):
    """Converts Sigma rule into LogPoint query"""
    identifier = "logpoint"
    active = True

    reEscape = re.compile('(["\\\\])')
    reClear = None
    andToken = " "
    orToken = " OR "
    notToken = " -"
    subExpression = "(%s)"
    listExpression = "[%s]"
    listSeparator = ", "
    valueExpression = "\"%s\""
    nullExpression = "-%s=*"
    notNullExpression = "%s=*"
    mapExpression = "%s=%s"
    mapListsSpecialHandling = True
    mapListValueExpression = "%s IN %s"
    
    def generateAggregation(self, agg):
        if agg == None:
            return ""
        if agg.aggfunc == sigma.parser.SigmaAggregationParser.AGGFUNC_NEAR:
            raise NotImplementedError("The 'near' aggregation operator is not yet implemented for this backend")
        if agg.groupfield == None:
            return " | chart %s(%s) as val | search val %s %s" % (agg.aggfunc_notrans, agg.aggfield, agg.cond_op, agg.condition)
        else:
            return " | chart %s(%s) as val by %s | search val %s %s" % (agg.aggfunc_notrans, agg.aggfield, agg.groupfield, agg.cond_op, agg.condition)
    
class SplunkBackend(SingleTextQueryBackend):
    """Converts Sigma rule into Splunk Search Processing Language (SPL)."""
    identifier = "splunk"
    active = True
    index_field = "index"

    reEscape = re.compile('(["\\\\])')
    reClear = None
    andToken = " "
    orToken = " OR "
    notToken = "NOT "
    subExpression = "(%s)"
    listExpression = "(%s)"
    listSeparator = " "
    valueExpression = "\"%s\""
    nullExpression = "NOT %s=\"*\""
    notNullExpression = "%s=\"*\""
    mapExpression = "%s=%s"
    mapListsSpecialHandling = True
    mapListValueExpression = "%s IN %s"

    def generateMapItemListNode(self, key, value):
        return "(" + (" OR ".join(['%s=%s' % (key, self.generateValueNode(item)) for item in value])) + ")"

    def generateAggregation(self, agg):
        if agg == None:
            return ""
        if agg.aggfunc == sigma.parser.SigmaAggregationParser.AGGFUNC_NEAR:
            raise NotImplementedError("The 'near' aggregation operator is not yet implemented for this backend")
        if agg.groupfield == None:
            return " | stats %s(%s) as val | search val %s %s" % (agg.aggfunc_notrans, agg.aggfield, agg.cond_op, agg.condition)
        else:
            return " | stats %s(%s) as val by %s | search val %s %s" % (agg.aggfunc_notrans, agg.aggfield, agg.groupfield, agg.cond_op, agg.condition)

class GrepBackend(BaseBackend, QuoteCharMixin):
    """Generates Perl compatible regular expressions and puts 'grep -P' around it"""
    identifier = "grep"
    active = True
    output_class = SingleOutput

    reEscape = re.compile("([\\|()\[\]{}.^$])")

    def generateQuery(self, parsed):
        return "grep -P '^%s'" % self.generateNode(parsed.parsedSearch)

    def cleanValue(self, val):
        val = super().cleanValue(val)
        return re.sub("\\*", ".*", val)

    def generateORNode(self, node):
        return "(?:%s)" % "|".join([".*" + self.generateNode(val) for val in node])

    def generateANDNode(self, node):
        return "".join(["(?=.*%s)" % self.generateNode(val) for val in node])

    def generateNOTNode(self, node):
        return "(?!.*%s)" % self.generateNode(node.item)

    def generateSubexpressionNode(self, node):
        return "(?:.*%s)" % self.generateNode(node.items)

    def generateListNode(self, node):
        if not set([type(value) for value in node]).issubset({str, int}):
            raise TypeError("List values must be strings or numbers")
        return self.generateORNode(node)

    def generateMapItemNode(self, node):
        key, value = node
        return self.generateNode(value)

    def generateValueNode(self, node):
        return self.cleanValue(str(node))

### Backends for developement purposes

class FieldnameListBackend(BaseBackend):
    """List all fieldnames from given Sigma rules for creation of a field mapping configuration."""
    identifier = "fieldlist"
    active = True
    output_class = SingleOutput

    def generateQuery(self, parsed):
        return "\n".join(sorted(set(list(flatten(self.generateNode(parsed.parsedSearch))))))

    def generateANDNode(self, node):
        return [self.generateNode(val) for val in node]

    def generateORNode(self, node):
        return self.generateANDNode(node)

    def generateNOTNode(self, node):
        return self.generateNode(node.item)

    def generateSubexpressionNode(self, node):
        return self.generateNode(node.items)

    def generateListNode(self, node):
        if not set([type(value) for value in node]).issubset({str, int}):
            raise TypeError("List values must be strings or numbers")
        return [self.generateNode(value) for value in node]

    def generateMapItemNode(self, node):
        key, value = node
        if type(value) not in (str, int, list):
            raise TypeError("Map values must be strings, numbers or lists, not " + str(type(value)))
        return [key]

    def generateValueNode(self, node):
        return []

# Helpers
def flatten(l):
  for i in l:
      if type(i) == list:
          yield from flatten(i)
      else:
          yield i

# Exceptions
class BackendError(Exception):
    """Base exception for backend-specific errors."""
    pass

class NotSupportedError(BackendError):
    """Exception is raised if some output is required that is not supported by the target language."""
    pass


#################################################

class ArcSightBackend(SingleTextQueryBackend):
    """Converts Sigma rule into ArcSight saved search."""
    identifier = "as"
    active = True

    andToken = " AND "
    orToken = " OR "
    notToken = "NOT "
    subExpression = "(%s)"
    listExpression = "(%s)"
    listSeparator = " OR "
    valueExpression = "\"%s\""
    containsExpression = "%s CONTAINS %s"
    nullExpression = "NOT _exists_:%s"
    notNullExpression = "_exists_:%s"
    mapExpression = "%s = %s"
    mapListsSpecialHandling = True
    mapListValueExpression = "%s = %s"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aFL = ["deviceVendor", "categoryDeviceGroup", "deviceProduct"]
        for item in self.sigmaconfig.fieldmappings.values():
            if item.target_type == list:
                aFL.extend(item.target)
            else:
                aFL.append(item.target)
        self.allowedFieldsList = list(set(aFL))

    def generateSCValueNodeLogsource(self, value):
        return self.valueExpression % (self.cleanValue(str(value)))

    def CleanNode(self, node):
        search_ptrn = re.compile(r"[\/\\@?#&_%*',\(\)\" ]")
        replace_ptrn = re.compile(r"[ \/\\@?#&_%*',\(\)\" ]")
        match = search_ptrn.search(node)
        new_node = list()
        if match:
            replaced_str = replace_ptrn.sub('*', node)
            node = [x for x in replaced_str.split('*') if x]
            new_node.extend(node)
        else:
            new_node.append(node)
        node = new_node
        return node

    def generateMapItemNode(self, node):
        key, value = node
        if key in self.allowedFieldsList:
            if self.mapListsSpecialHandling == False and type(value) in (
                    str, int, list) or self.mapListsSpecialHandling == True and type(value) in (str, int):
                return self.mapExpression % (key, self.generateSCValueNodeLogsource(value))
            elif type(value) == list:
                return self.generateMapItemListNode(key, value)
            else:
                raise TypeError("Backend does not support map values of type " + str(type(value)))

        else:
            if self.mapListsSpecialHandling == False and type(value) in (
                    str, int, list) or self.mapListsSpecialHandling == True and type(value) in (str, int):
                if type(value) == str:
                    new_value = list()
                    value = self.CleanNode(value)
                    if type(value) == list:
                        new_value.append(self.andToken.join([self.valueExpression % val for val in value]))
                    else:
                        new_value.append(value)
                    if len(new_value)==1:
                        return "(" + self.generateANDNode(new_value) + ")"
                    else:
                        return "(" + self.generateORNode(new_value) + ")"
                else:
                    return self.generateValueNode(value)
            elif type(value) == list:
                new_value = list()
                for item in value:
                    item = self.CleanNode(item)
                    if type(item) == list and len(item) == 1:
                        new_value.append(self.valueExpression % item[0])
                    elif type(item) == list:
                        new_value.append(self.andToken.join([self.valueExpression % val for val in item]))
                    else:
                        new_value.append(item)
                return self.generateORNode(new_value)
            else:
                raise TypeError("Backend does not support map values of type " + str(type(value)))

    def generateValueNode(self, node):
        if type(node) == int:
            return self.cleanValue(str(node))
        if 'AND' in node:
            return "(" + self.cleanValue(str(node)) + ")"
        else:
            return self.cleanValue(str(node))

    def generateMapItemListNode(self, key, value):
        itemslist = list()
        for item in value:
            if key in self.allowedFieldsList:
                itemslist.append('%s = %s' % (key, self.generateValueNode(item)))
            else:
                itemslist.append('%s' % (self.generateValueNode(item)))
        return " OR ".join(itemslist)

    def generate(self, sigmaparser):
        """Method is called for each sigma rule and receives the parsed rule (SigmaParser)"""
        const_title = ' AND type != 2 | rex field = flexString1 mode=sed "s//Sigma: {}/g"'
        for parsed in sigmaparser.condparsed:
            self.output.print(self.generateQuery(parsed) + const_title.format(sigmaparser.parsedyaml["title"]))

    def generateSubexpressionNode(self, node):
        return self.subExpression % self.generateNode(node.items)

    def generateORNode(self, node):
        if type(node) == sigma.parser.ConditionOR and all(isinstance(item, str) for item in node):
            new_value = list()
            for value in node:
                value = self.CleanNode(value)
                if type(value) == list:
                    new_value.append(self.andToken.join([self.valueExpression % val for val in value]))
                else:
                    new_value.append(value)
            return "(" + self.orToken.join([self.generateNode(val) for val in new_value]) + ")"
        return "(" + self.orToken.join([self.generateNode(val) for val in node]) + ")"



######################################################################################################################

class QualysBackend(SingleTextQueryBackend):
    """Converts Sigma rule into Qualys saved search."""
    identifier = "qualys"
    active = True
    andToken = " and "
    orToken = " or "
    notToken = "not "
    subExpression = "(%s)"
    listExpression = "%s"
    listSeparator = " "
    valueExpression = "%s"
    nullExpression = "%s is null"
    notNullExpression = "not (%s is null)"
    mapExpression = "%s:`%s`"
    mapListsSpecialHandling = True
    PartialMatchFlag = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fl = []
        for item in self.sigmaconfig.fieldmappings.values():
            if item.target_type == list:
                fl.extend(item.target)
            else:
                fl.append(item.target)
        # print(fl)
        self.allowedFieldsList = list(set(fl))
        # if 'event.id' in self.allowedFieldsList:
        #     self.allowedFieldsList.remove('event.id')
        # else:
        #     pass

    def find_keys(self, dct):
        for k, v in dct.items():
            if isinstance(v, dict):
                for x in self.find_keys(v):
                    yield "{}".format(x)
            else:
                yield k

    # def generateANDNode(self, node):
    #     print('generateANDNode', node.items[0], type(node.items[0]))
    #     for val in node:
    #         if type(val) == tuple and val[0] in self.allowedFieldsList:
    #             return self.andToken.join(self.generateNode(val))

    def generateORNode(self, node):
        # print('generateORNode', node.items[0], type(node.items[0]))
        new_list = []
        for val in node:
            if type(val) == tuple and not(val[0] in self.allowedFieldsList):
                pass
                # self.PartialMatchFlag = True
            else:
                new_list.append(val)

        return self.orToken.join([self.generateNode(val) for val in new_list])

    def generateANDNode(self, node):
        # print('generateANDNode', node.items[0], type(node.items[0]))
        new_list = []
        for val in node:
            if type(val) == tuple and not(val[0] in self.allowedFieldsList):
                self.PartialMatchFlag = True
            else:
                new_list.append(val)
        return self.andToken.join([self.generateNode(val) for val in new_list])

    def generateMapItemNode(self, node):
        key, value = node
        if self.mapListsSpecialHandling == False and type(value) in (str, int, list) or self.mapListsSpecialHandling == True and type(value) in (str, int):
            if key in self.allowedFieldsList:
                return self.mapExpression % (key, self.generateNode(value))
            else:
                return self.generateNode(value)
        elif type(value) == list:
            return self.generateMapItemListNode(key, value)
        else:
            raise TypeError("Backend does not support map values of type " + str(type(value)))

    def generateMapItemListNode(self, key, value):
        # print("generateMapItemListNode", self.sigmaconfig.fieldmappings.keys())
        itemslist = []
        for item in value:
            if key in self.allowedFieldsList:
                itemslist.append('%s:`%s`' % (key, self.generateValueNode(item)))
            else:
                itemslist.append('%s' % (self.generateValueNode(item)))
        #['%s:`%s`' % (key, self.generateValueNode(item)) for item in value]
        return "(" + (" or ".join(itemslist)) + ")"

    def generate(self, sigmaparser):
        """Method is called for each sigma rule and receives the parsed rule (SigmaParser)"""
        all_keys = set()

        for parsed in sigmaparser.condparsed:
            if self.generateQuery(parsed) == "()":
                self.PartialMatchFlag = None
            sigmaparser_parsedyaml = sigmaparser.parsedyaml
            # a = self.find_keys(sigmaparser_parsedyaml)
            # all_keys.update(a)
            # print(self.PartialMatchFlag)
            if self.PartialMatchFlag == True:
                raise PartialMatchError(self.generateQuery(parsed))
            elif self.PartialMatchFlag == None:
                raise FullMatchError(self.generateQuery(parsed))
            else:
                print(self.generateQuery(parsed))


class PartialMatchError(Exception):
    pass

class FullMatchError(Exception):
    pass


class QRadarBackend(SingleTextQueryBackend):

    identifier = "qradar"
    active = True
    andToken = " and "
    orToken = " or "
    notToken = "not "
    subExpression = "(%s)"
    listExpression = "%s"
    listSeparator = " "
    valueExpression = "\'%s\'"
    keyExpression = "\"%s\""
    nullExpression = "%s is null"
    notNullExpression = "not (%s is null)"
    mapExpression = "%s=%s"
    mapListsSpecialHandling = True
    allKeys_aFL = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.allKeys_aFL = True
        aFL = ["deviceVendor", "categoryDeviceGroup", "deviceProduct"]
        for item in self.sigmaconfig.fieldmappings.values():
            if item.target_type == list:
                aFL.extend(item.target)
            else:
                aFL.append(item.target)
        self.allowedFieldsList = list(set(aFL))


    def generateANDNode(self, node):

        return '(' + self.andToken.join([self.generateNode(val) for val in node]) + ')'

    def generateORNode(self, node):

        return '('+self.orToken.join([self.generateNode(val) for val in node])+')'

    def generateNOTNode(self, node):

        return self.notToken + self.generateNode(node.item)

    def generateSubexpressionNode(self, node):

        return self.subExpression % self.generateNode(node.items)

    def generateListNode(self, node):

        if not set([type(value) for value in node]).issubset({str, int}):
            raise TypeError("List values must be strings or numbers")
        return self.listExpression % (self.listSeparator.join([self.generateNode(value) for value in node]))

    def generateSCValueNodeLogsource(self, value):

        if value == 'Microsoft':
            if self.allKeys_aFL == True:
                self.const_start = "*"
            return self.cleanValue(str(value))

        else:
            if self.allKeys_aFL == True:
                self.const_start = "*"
            return self.cleanValue(str(value))


    def generateMapItemNode(self, node):
        key, value = node

        if key in self.allowedFieldsList:
            if key == 'deviceProduct':
                return self.generateSCValueNodeLogsource(value)
            if self.mapListsSpecialHandling == False and type(value) in (
                    str, int, list) or self.mapListsSpecialHandling == True and type(value) in (str, int):
                return self.mapExpression % (self.keyExpression % key, self.valueExpression % self.generateSCValueNodeLogsource(value))
            elif type(value) == list:
                return self.generateMapItemListNode(key, value)
            else:
                raise TypeError("Backend does not support map values of type " + str(type(value)))

        else:

            if self.mapListsSpecialHandling == False and type(value) in (
                    str, int, list) or self.mapListsSpecialHandling == True and type(value) in (str, int):
                if type(value) == str:
                    new_value = list()

                    if type(value) == list:
                        new_value.append(self.andToken.join([val for val in value]))
                    else:
                        new_value.append(value)
                    if len(new_value)==1:
                        return self.generateValueNode(value)
                    else:
                        return "(" + self.generateORNode(new_value) + ")"
                else:
                    return self.generateValueNode(value)
            elif type(value) == list:
                new_value = list()
                for item in value:
                    # item = self.CleanNode(item)
                    if type(item) == list and len(item) == 1:
                        new_value.append(self.valueExpression % item[0])
                    elif type(item) == list:
                        new_value.append(self.andToken.join([val for val in item]))
                    else:
                        new_value.append(item)
                return self.generateORNode(new_value)
            else:
                raise TypeError("Backend does not support map values of type " + str(type(value)))

    def generateMapItemListNode(self, key, value):

        itemslist = list()
        for item in value:
            # print('generateMapItemListNode', 'item', item, key)
            if key in self.allowedFieldsList:
                itemslist.append('%s = %s' % (self.keyExpression % key, self.valueExpression % self.generateSCValueNodeLogsource(item)))
            else:
                itemslist.append('%s' % (self.generateValueNode(item)))
        return '('+" or ".join(itemslist)+')'

    def generateValueNode(self, node):
        # print('generateValueNode', node, type(node))
        if type(node) == str and "*" in node:
            self.node = node.replace("*", "%")
            return "{} '{}'".format("search_payload ilike", self.cleanValue(str(self.node)))
        return "{} '{}'".format("search_payload ilike", self.cleanValue(str(node)))

    def generateNULLValueNode(self, node):

        return self.nullExpression % (node.item)

    def generateNotNULLValueNode(self, node):

        return self.notNullExpression % (node.item)

    def generate(self, sigmaparser):

        self.const_start = "SELECT UTF8(payload) as search_payload from events where "
        for parsed in sigmaparser.condparsed:
            self.output.print(self.const_start + self.generateQuery(parsed))




class GraylogQuerystringBackend(SingleTextQueryBackend):
    """Converts Sigma rule into Graylog query string. Only searches, no aggregations."""
    identifier = "graylog"
    active = True

    reEscape = re.compile("([+\\-!(){}\\[\\]^\"~:/]|\\\\(?![*?])|&&|\\|\\|)")
    reClear = None
    andToken = " AND "
    orToken = " OR "
    notToken = "NOT "
    subExpression = "(%s)"
    listExpression = "(%s)"
    listSeparator = " "
    valueExpression = "\"%s\""
    nullExpression = "NOT _exists_:%s"
    notNullExpression = "_exists_:%s"
    mapExpression = "%s:%s"
    mapListsSpecialHandling = False
