/* Copyright 2015 VMware, Inc.  All rights reserved. -- VMware Confidential */

(function() {

   "use strict";

   var MIME_TYPE = "text/xml";
   var SOAP_NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/";
   var WSDL_NAMESPACE = "http://schemas.xmlsoap.org/wsdl/";
   var XML_NAMESPACE = "http://www.w3.org/2000/xmlns/";
   var XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema";
   var XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance";

   var SOAP_ACTION_INDEX = 0;
   var INPUT_INDEX = 1;
   var OUTPUT_INDEX = 2;
   var FAULTS_INDEX = 3;
   var NS_INDEX = 0;
   var NAME_INDEX = 1;

   var WSDL_REPO = ""; // "https://engweb.eng.vmware.com/~rhristov/wsdl";

   var parser = new (isUndefined(typeof DOMParser) ? require("xmldom").DOMParser : DOMParser)();
   var serializer = new (isUndefined(typeof XMLSerializer) ? require("xmldom").XMLSerializer : XMLSerializer)();
   var storage = isUndefined(typeof localStorage) ? new (require("node-localstorage").LocalStorage)(
         require("path").join(__dirname, ".localStorage")) : localStorage;
   var ab = isUndefined(typeof atob) ? require("atob") : atob;
   var ba = isUndefined(typeof btoa) ? require("btoa") : btoa;
   var proxies = typeof Proxy === "function";
   var xmlDocument = isUndefined(typeof document) ? parser.parseFromString("<xml/>") : document;

   var memoize = (function() {
      var memoized = [];
      var memoize = function(fn) {
         var cache = {};
         var f = function() {
            var hash = JSON.stringify(arguments);
            return (hash in cache) ? cache[hash] : cache[hash] = fn.apply(this,
               arguments);
         };
         f.clearCache = function() {
            cache = {};
         };
         memoized.push(f);
         return f;
      };
      memoize.clearCache = function() {
         memoized.forEach(function(f) {
            f.clearCache();
         });
      };
      return memoize;
   })();

   function isUndefined(value) {
      return value === undefined || value === "undefined";
   }

   function isNull(value) {
      return value === null;
   }

   function isObject(value) {
      return typeof value === "object";
   }

   function isArrayType(type) {
      return /^ArrayOf/.test(type);
   }

   function attr(element, name) {
      return element.getAttribute(name);
   }

   function defineProperty(obj, prop, descriptor) {
      Object.defineProperty(obj, prop, descriptor);
   }

   function keys(obj) {
      return Object.keys(obj);
   }

   function merge() {
      var result = {};
      for (var i = 0, j = arguments.length; i !== j; ++i) {
         var obj = arguments[i];
         var props = keys(obj);
         for (var k = 0, l = props.length; k !== l; ++k) {
            var prop = props[k];
            result[prop] = isObject(result[prop]) && isObject(obj[prop]) ?
               merge(result[prop], obj[prop]) : obj[prop];
         }
      }
      return result;
   }

   function lookupNamespaceURI(node, prefix) {
      return node.lookupNamespaceURI(prefix);
   }

   function getByNameNS(element, namespace, name) {
      return element.getElementsByTagNameNS(namespace, name);
   }

   function parseResponse(req) {
      if (req.responseXML && req.responseXML.querySelector) {
         return req.responseXML;
      } else {
         return parser.parseFromString(req.responseText, MIME_TYPE);
      }
   }

   function parseUrl(url) {
      // RFC 3986 Appendix B
      var pattern = new RegExp("^(([^:/?#]+):)?(//([^/?#]*))?([^?#]*)(\\?([^#]*))?(#(.*))?");
      var matches = url.match(pattern);
      return {
         scheme: matches[2],
         authority: matches[4],
         path: matches[5],
         query: matches[7],
         fragment: matches[9]
      };
   }

   function createElementNS(namespace, name) {
      if (!isUndefined(xmlDocument.firstChild.getAttribute) &&
         !isNull(xmlDocument.firstChild.getAttribute("lineNumber"))) {
         // Workaround for xmldom issue #45
         var el = xmlDocument.createElement(name);
         el.setAttribute("xmlns", namespace);
         return el;
      } else {
         return xmlDocument.createElementNS(namespace, name);
      }
   }

   function createDocumentNS(namespace, name) {
      if (!isUndefined(xmlDocument.firstChild.getAttribute) &&
         !isNull(xmlDocument.firstChild.getAttribute("lineNumber"))) {
         // Workaround for xmldom issue #45
         var doc = xmlDocument.implementation.createDocument(null, name, null);
         doc.firstChild.setAttribute("xmlns", namespace);
         return doc;
      } else {
         return xmlDocument.implementation.createDocument(namespace, name, null);
      }
   }

   function createTextNode(text) {
      return xmlDocument.createTextNode(text);
   }

   function createTransport(options, success, error) {
      var target = "https://" + options.hostname;
      options.headers = options.headers || {};
      if (options.proxy) {
         options.headers[options.proxyHeader] = target;
      }
      if (options.csrfToken) {
         options.headers[options.csrfTokenHeader] = options.csrfToken;
      }
      var components = parseUrl(options.url);
      var req = new (isUndefined(typeof XMLHttpRequest) ?
         require("xmlhttprequest-cookie").XMLHttpRequest : XMLHttpRequest)();
      req.open(options.type, (options.proxy ? "" : target) +
         components.path + (isUndefined(components.query) ? "" : "?" + components.query));
      if (!isUndefined(req.overrideMimeType)) {
         req.overrideMimeType(MIME_TYPE);
      }
      req.withCredentials = true;
      keys(options.headers).forEach(function(name) {
         if (!isUndefined(options.headers[name])) {
            req.setRequestHeader(name, options.headers[name]);
         }
      });
      req.onreadystatechange = function() {
         if (req.readyState === 4) {
            if (req.status === 200) {
               success(req);
            } else {
               error(req);
            }
         }
      };
      if (options.data) {
         req.send(options.data);
      } else {
         req.send();
      }
   }

   function getResponseHeaders(req) {
      var headers = {};
      var str = req.getAllResponseHeaders();
      if (str) {
         var pairs = str.split("\u000d\u000a");
         for (var i = 0, j = pairs.length; i !== j; ++i) {
            var pair = pairs[i];
            var index = pair.indexOf("\u003a\u0020");
            if (index > 0) {
               var key = pair.substring(0, index);
               var val = pair.substring(index + 2);
               headers[key] = val;
            }
         }
      }
      return headers;
   }

   var defaults = {
      prefixes: {
         "http://www.w3.org/2001/XMLSchema": "xsd"
      },
      proxyHeader: "X-vSphere-Proxy",
      connect: function(options) {
         return new Promise(function(resolve) {
            options.storageKey = options.serviceName;
            resolve({});
         });
      },
      serialize: function(operation, name, exports, args, type) {
         var envelope = createDocumentNS(SOAP_NAMESPACE, "Envelope").documentElement;
         envelope.setAttributeNS(XML_NAMESPACE, "xmlns:xsi", XSI_NAMESPACE);
         var body = envelope.appendChild(createElementNS(SOAP_NAMESPACE, "Body"));
         var inputType = operation[INPUT_INDEX].type;
         var ns = exports.namespaces[inputType[NS_INDEX]];
         var requestObject = new exports.typeFunctions[ns.name][ns.types[inputType[NAME_INDEX]]]();
         type.elements.filter(function(el) {
            return !isUndefined(el.name);
         }).forEach(function(el, index) {
            requestObject[el.name] = args[index];
         });
         body.appendChild(exports.serializeObject(
            requestObject, operation[INPUT_INDEX].name, operation[INPUT_INDEX].type));
         return envelope;
      },
      deserialize: function(envelope, operation, name, exports) {
         var outputType = operation[OUTPUT_INDEX].type;
         var node = getByNameNS(envelope, exports.namespaces[outputType[NS_INDEX]].name,
            operation[OUTPUT_INDEX].name)[0];
         var result = exports.deserializeObject(operation[OUTPUT_INDEX].type, node);
         return result[keys(result)[0]];
      }
   };

   function soapService(hostname, options) {

      var exports = {
         serializeObject: serializeObject,
         deserializeObject: deserializeObject
      };
      var handlerChain = new Set();
      var namespaces;
      var operations;
      var operationFunctions;
      var typeFunctions;
      var typeNames = new Map();
      var types;
      var service = {};
      var xmlMessages = {};
      var xmlOperations = {};
      var xmlBindings = {};
      var xmlTypes = {};
      var xmlElements = {};
      var xmlAttributes = {};
      var xmlAttributeGroups = {};
      var storageKey = findStorageKey();

      var isXsdType = memoize(function(type) {
         return getTypeNamespace(type) === 0;
      });

      var getElements = memoize(function(name) {
         var type = getType(name);
         var elements = type.elements || [];
         var base = type.base;
         if (!isUndefined(base) && !isXsdType(base)) {
            elements = getElements(base).concat(elements);
         }
         return elements;
      });

      var getAttributes = memoize(function(name) {
         var type = getType(name);
         var attributes = isUndefined(type.attributes) ? [] : type.attributes;
         var base = type.base;
         if (!isUndefined(base) && !isXsdType(base)) {
            attributes = getAttributes(base).concat(attributes);
         }
         return attributes;
      });

      var getBase = memoize(function(type) {
         if (isXsdType(type)) {
            return type;
         }
         var base = getType(type).base;
         if (!isUndefined(base)) {
            return getBase(base);
         }
         return base;
      });

      var getNSIndex = memoize(function(namespace) {
         for (var i = 0; i !== namespaces.length; ++i) {
            if (namespaces[i].name === namespace) {
               return i;
            }
         }
      });

      var getTypeIndex = memoize(function(ns, type) {
         return namespaces[ns].types.indexOf(type);
      });

      function getClass(ns, type) {
         return typeFunctions[ns.name][ns.types[getTypeName(type)]];
      }

      function getNamespace(type) {
         return namespaces[getTypeNamespace(type)];
      }

      function getTypeNamespace(type) {
         return type[NS_INDEX];
      }

      function getTypeName(type) {
         return type[NAME_INDEX];
      }

      function getType(type) {
         return types[getTypeNamespace(type)][getTypeName(type)];
      }

      function load(url, cache, success, error) {
         if (!isUndefined(cache[url])) {
            if (!isUndefined(cache[url].data)) {
               success(cache[url].data);
            } else {
               cache[url].success.push(success);
               cache[url].error.push(error);
            }
         } else {
            cache[url] = {
               success: [success],
               error: [error]
            };
            createTransport({
               hostname: parseUrl(url).authority || hostname,
               proxy: options.proxy,
               proxyHeader: options.proxyHeader,
               csrfToken: options.csrfToken,
               csrfTokenHeader: options.csrfTokenHeader,
               type: "GET",
               url: url
            }, function(req) {
               var data = parseResponse(req);
               var wsdlImports = getByNameNS(data, WSDL_NAMESPACE, "import");
               var xsdImports = getByNameNS(data, XSD_NAMESPACE, "import");
               var xsdIncludes = getByNameNS(data, XSD_NAMESPACE, "include");
               cache[url].length = wsdlImports.length + xsdImports.length + xsdIncludes.length;
               cache[url].data = data;
               if (cache[url].length === 0) {
                  processResponse(cache[url].data);
                  cache[url].success.forEach(function(el) {
                     el(cache[url].data);
                  });
               } else {
                  var i, j;
                  for (i = 0, j = wsdlImports.length; i !== j; ++i) {
                     loadLink(url, cache, wsdlImports[i]);
                  }
                  for (i = 0, j = xsdImports.length; i !== j; ++i) {
                     loadLink(url, cache, xsdImports[i]);
                  }
                  for (i = 0, j = xsdIncludes.length; i !== j; ++i) {
                     loadLink(url, cache, xsdIncludes[i]);
                  }
               }
            }, function(req) {
               cache[url].error.forEach(function(el) {
                  el(req.statusText);
               });
            });
         }
      }

      function loadLink(url, cache, element) {
         var location = attr(element, "location") || attr(element, "schemaLocation");
         var components = parseUrl(location);
         if (!isUndefined(components.scheme)) {
            location = components.path + (components.query ? "?" + components.query : "");
         } else if (components.path.indexOf("/") !== 0) {
            location = url.replace(/[^\/]+$/, location);
         }
         load(location, cache, function() {
            cache[url].length--;
            if (cache[url].length === 0) {
               processResponse(cache[url].data);
               cache[url].success.forEach(function(el) {
                  el(cache[url].data);
               });
            }
         }, function(data) {
            cache[url].error.forEach(function(el) {
               el(data);
            });
         });
      }

      function processResponse(doc) {
         var definitions = getByNameNS(doc, WSDL_NAMESPACE, "definitions");
         var targetNS, node, i, j, k, l, m, n, o, p;
         for (i = 0, j = definitions.length; i !== j; ++i) {
            targetNS = attr(definitions[i], "targetNamespace");
            xmlMessages[targetNS] = xmlMessages[targetNS] || {};
            xmlOperations[targetNS] = xmlOperations[targetNS] || {};
            xmlBindings[targetNS] = xmlBindings[targetNS] || {};
            for (k = 0, l = definitions[i].childNodes.length; k !== l; ++k) {
               node = definitions[i].childNodes[k];
               switch (node.localName) {
                  case "message":
                     xmlMessages[targetNS][attr(node, "name")] = node;
                     break;
                  case "portType":
                     for (m = 0, n = node.childNodes.length; m !== n; ++m) {
                        if (node.childNodes[m].localName === "operation") {
                           xmlOperations[targetNS][attr(node.childNodes[m], "name")] =
                              node.childNodes[m];
                        }
                     }
                     break;
                  case "binding":
                     for (m = 0, n = node.childNodes.length; m !== n; ++m) {
                        if (node.childNodes[m].localName === "operation") {
                           var subnode = node.childNodes[m];
                           var operation = attr(subnode, "name");
                           for (o = 0, p = subnode.childNodes.length; o !== p; ++o) {
                              if (subnode.childNodes[o].localName === "operation") {
                                 xmlBindings[targetNS][operation] = subnode.childNodes[o];
                              }
                           }
                        }
                     }
                     break;
               }
            }
         }
         var schemas = getByNameNS(doc, XSD_NAMESPACE, "schema");
         for (i = 0, j = schemas.length; i !== j; ++i) {
            targetNS = attr(schemas[i], "targetNamespace");
            if (isNull(targetNS)) {
               continue;
            }
            xmlAttributes[targetNS] = xmlAttributes[targetNS] || {};
            xmlTypes[targetNS] = xmlTypes[targetNS] || {};
            xmlElements[targetNS] = xmlElements[targetNS] || {};
            xmlAttributeGroups[targetNS] = xmlAttributeGroups[targetNS] || {};
            for (k = 0, l = schemas[i].childNodes.length; k !== l; ++k) {
               node = schemas[i].childNodes[k];
               switch (node.localName) {
                  case "attribute":
                     xmlAttributes[targetNS][attr(node, "name")] = node;
                     break;
                  case "complexType":
                  case "simpleType":
                     xmlTypes[targetNS][attr(node, "name")] = node;
                     break;
                  case "element":
                     var name = attr(node, "name");
                     xmlElements[targetNS][name] = node;
                     for (m = 0, n = node.childNodes.length; m !== n; ++m) {
                        switch (node.childNodes[m].localName) {
                           case "complexType":
                           case "simpleType":
                              xmlTypes[targetNS][name] = node.childNodes[m];
                              xmlTypes[targetNS][name].setAttribute("name", name);
                              xmlElements[targetNS][name].setAttribute("type",
                                 node.lookupPrefix(targetNS) + ":" + name);
                              break;
                        }
                     }
                     break;
                  case "attributeGroup":
                     xmlAttributeGroups[targetNS][attr(node, "name")] = node;
                     break;
               }
            }
         }
      }

      function getObjectType(obj) {
         if (isObject(obj)) {
            return typeNames.get(obj.constructor);
         }
      }

      function inherit(type) {
         var ns = getNamespace(type);
         var clazz = getClass(ns, type);
         typeNames.set(clazz, type);
         var properties = {};
         type = getType(type);
         (type.elements || []).concat(type.attributes || [])
            .filter(function(el) {
               return !isUndefined(el.name);
            }).forEach(function(el) {
               properties[el.name] = {
                  enumerable: true,
                  writable: true
               };
            });
         var base = type.base;
         var superclazz = Object;
         if (!isUndefined(base)) {
            if (isXsdType(base)) {
               properties.value = {
                  enumerable: true,
                  writable: true
               };
            } else {
               ns = getNamespace(base);
               superclazz = getClass(ns, base);
               if (isUndefined(typeNames.get(superclazz))) {
                  inherit(base);
               }
            }
         }
         properties.constructor = {
            value: clazz
         };
         clazz.prototype = Object.create(superclazz.prototype, properties);
      }

      function executeConstructor(type, obj) {
         var self = this;
         var ns = getNamespace(type);
         if (isUndefined(typeNames.get(getClass(ns, type)))) {
            inherit(type);
            self = createInstance(type, null, isUndefined(obj) ? [] : [obj]);
         }
         return isUndefined(obj) ? self : Object.assign(self, obj);
      }

      function executeOperation(name, args) {
         return new Promise(function(resolve, reject) {
            var operation = operations[name];
            var input = operation[INPUT_INDEX].type;
            var headers = {
               "Content-Type": "text/xml",
               SOAPAction: operation[SOAP_ACTION_INDEX]
            };
            var envelope = options.serialize(operation, name, exports, args, getType(input));
            var values = handlerChain.values();
            var handler = values.next();
            while (handler.done === false) {
               if (handler.value({envelope: envelope, outgoing: true, headers: headers}) === false) {
                  break;
               }
               handler = values.next();
            }
            var data = serializer.serializeToString(envelope).replace(
               "<Envelope xmlns=\"http://schemas.xmlsoap.org/soap/envelope/\">",
               "<Envelope xmlns=\"http://schemas.xmlsoap.org/soap/envelope/\" " +
                  "xmlns:xs=\"http://www.w3.org/2001/XMLSchema\" " +
                  "xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">");
            createTransport({
               data: data,
               headers: headers,
               hostname: hostname,
               proxy: options.proxy,
               proxyHeader: options.proxyHeader,
               csrfToken: options.csrfToken,
               csrfTokenHeader: options.csrfTokenHeader,
               type: "POST",
               url: options.sdk
            }, function(req) {
               var envelope = parseResponse(req);
               var values = handlerChain.values();
               var handler = values.next();
               var headers = getResponseHeaders(req);
               if (isUndefined(typeof XMLHttpRequest)) {
                  var cookie = req.getResponseHeader("set-cookie");
                  if (!isUndefined(cookie)) {
                     headers["set-cookie"] = cookie;
                  }
               }
               while (handler.done === false) {
                  if (handler.value({envelope: envelope, outgoing: false, headers: headers}) === false) {
                     break;
                  }
                  handler = values.next();
               }
               resolve(options.deserialize(envelope, operation, name, exports));
            }, function(req) {
               reject(req.status === 500 ? deserializeFault(operation,
                  parseResponse(req)) : req.statusText);
            });
         });
      }

      function createInstance(type, target, args) {
         var ns = getNamespace(type);
         target = Object.create(getClass(ns, type).prototype);
         getClass(ns, type).apply(target, args);
         return target;
      }

      function createClass(type) {
         if (isArrayType(getNamespace(type).types[getTypeName(type)])) {
            return Array;
         }
         if (proxies) {
            return new Proxy(function(obj) {
               return Object.assign(this, obj);
            }, {
               construct: createInstance.bind(null, type),
               get: function(target, property) {
                  var ns = getNamespace(type);
                  if (property === "prototype" &&
                     isUndefined(typeNames.get(getClass(ns, type)))) {
                     inherit(type);
                  }
                  return target[property];
               }
            });
         }
         return function(obj) {
            return executeConstructor.call(this, type, obj);
         };
      }

      function createMethod(name) {
         return function() {
            return executeOperation.call(this, name, arguments);
         };
      }

      function createProperties() {
         exports.typeFunctions = typeFunctions = {};
         exports.operationFunctions = operationFunctions = {};
         exports.namespaces = namespaces;
         namespaces.forEach(function(ns, nsIndex) {
            typeFunctions[ns.name] = {};
            ns.types.forEach(function(name, nameIndex) {
               defineProperty(typeFunctions[ns.name], name, {
                  enumerable: true,
                  value: createClass([nsIndex, nameIndex])
               });
            });
         });
         keys(operations).forEach(function(name) {
            var methodName = name.charAt(0).toLowerCase() + name.substr(1);
            defineProperty(operationFunctions, methodName, {
               enumerable: true,
               value: createMethod(name)
            });
         });
      }

      function isValidEnumValue(type, value) {
         var match = type.enumerations.indexOf(value) !== -1;
         return match || type.enumerations.length === 0 || type.unions
            .some(function(union) {
               return isXsdType(union) ||
                  isValidEnumValue(getType(union), value);
            });
      }

      function parseRef(node, ref, defaultNS) {
         var typeName = ref.split(":"), ns, name;
         if (typeName.length === 2) {
            ns = lookupNamespaceURI(node, typeName[0]);
            name = typeName[1];
         } else {
            ns = defaultNS || XSD_NAMESPACE;
            name = typeName[0];
         }
         var nsIndex = getNSIndex(ns);
         var typeIndex = getTypeIndex(nsIndex, name);
         // Namespace lookup required by the internal VCDP API
         if (typeIndex === -1) {
            for (var i = 0; i !== namespaces.length; ++i) {
               typeIndex = getTypeIndex(i, name);
               if (typeIndex !== -1) {
                  nsIndex = i;
                  break;
               }
            }
         }
         return [nsIndex, typeIndex];
      }

      function toProperty(node, refs) {
         var obj = {};
         for (var i = 0, l = node.attributes.length; i !== l; ++i) {
            var name = node.attributes[i].name;
            var value = node.attributes[i].value;
            if (name === "ref") {
               var elementName = value.split(":");
               var ref = refs[lookupNamespaceURI(node, elementName[0])][elementName[1]];
               obj.name = attr(ref, "name");
               obj.type = parseRef(ref, attr(ref, "type"));
            } else if (name === "type") {
               obj.type = parseRef(node, value);
            } else {
               obj[name] = value;
            }
         }
         return obj;
      }

      function toString(value, type) {
         switch (getNamespace(type).types[getTypeName(type)]) {
            case "anyType":
            case "anyURI":
            case "boolean":
            case "byte":
            case "date":
            case "dateTime":
            case "float":
            case "ID":
            case "int":
            case "long":
            case "negativeInteger":
            case "nonNegativeInteger":
            case "nonPositiveInteger":
            case "positiveInteger":
            case "short":
            case "string":
               return value;
            case "base64Binary":
               return ba(value);
            default:
               throw new Error("Trying to format an unexpected type as a string");
         }
      }

      function fromString(value, type) {
         switch (getNamespace(type).types[getTypeName(type)]) {
            case "anyURI":
            case "string":
               return value;
            case "base64Binary":
               return ab(value.replace(/\s/g, ""));
            case "boolean":
               return value.toLowerCase() === "true";
            case "byte":
            case "int":
            case "long":
            case "negativeInteger":
            case "nonNegativeInteger":
            case "nonPositiveInteger":
            case "positiveInteger":
            case "short":
               return parseInt(value);
            case "dateTime":
               return new Date(value);
            case "float":
               return parseFloat(value);
            default:
               throw new Error("Unknown xsd type");
         }
      }

      function serializeObject(obj, tag, type) {
         var objectTypeName = getObjectType(obj);
         if (isUndefined(objectTypeName)) {
            throw new Error("Unknown type");
         }
         var objectType = getType(objectTypeName), element;
         if (!isUndefined(type)) {
            element = createElementNS(getNamespace(type).name, tag);
            if (getTypeNamespace(objectTypeName) !== getTypeNamespace(type) ||
               getTypeName(objectTypeName) !== getTypeName(type)) {
               var ns = getNamespace(type);
               if (!isUndefined(typeFunctions[ns.name]) && !(ns.types[getTypeName(type)] === "anyType" ||
                     obj instanceof getClass(ns, type))) {
                  throw new Error("Unexpected object type");
               }
               element.setAttributeNS(XSI_NAMESPACE, "xsi:type",
                  getNamespace(objectTypeName).types[getTypeName(objectTypeName)]);
            }
         } else {
            element = createElementNS(getNamespace(objectTypeName).name, tag);
         }
         var props = keys(obj), any;
         getElements(objectTypeName).forEach(function(el) {
            if (isUndefined(el.name)) {
               any = el;
            } else {
               if (isUndefined(obj[el.name]) || isNull(obj[el.name])) {
                  var minOccurs = el.minOccurs || objectType.minOccurs;
                  if (minOccurs !== "0") {
                     throw new Error("Required property not defined: " + el.name);
                  }
               } else {
                  var objects = Array.isArray(obj[el.name]) ? obj[el.name] : [obj[el.name]];
                  objects.forEach(function(obj) {
                     var child;
                     if (!isObject(obj) && isXsdType(el.type)) {
                        child = createElementNS(getNamespace(objectTypeName).name, el.name);
                        child.appendChild(createTextNode(toString(obj, el.type)));
                     } else {
                        var childType = isXsdType(el.type) ? {} : getType(el.type);
                        if (!isUndefined(childType.enumerations)) {
                           if (!isValidEnumValue(childType, obj.value)) {
                              throw new Error("Invalid enum value");
                           }
                           child = createElementNS(getNamespace(el.type).name, el.name);
                           child.appendChild(createTextNode(obj.value));
                        } else {
                           child = serializeObject(obj, el.name, el.type);
                        }
                     }
                     element.appendChild(child);
                  });
               }
               props = props.filter(function(prop) {
                  return prop !== el.name;
               });
            }
         });
         var anyAttribute;
         getAttributes(objectTypeName).forEach(function(el) {
            if (isUndefined(el.name)) {
               anyAttribute = el;
            } else {
               if (isUndefined(obj[el.name]) || isNull(obj[el.name])) {
                  if (el.use === "required") {
                     throw new Error("Required attribute not defined");
                  }
               } else {
                  if (isXsdType(el.type)) {
                     element.setAttribute(el.name, toString(obj[el.name], el.type));
                  } else {
                     var type = getType(el.type);
                     if (!isValidEnumValue(type, obj[el.name].value)) {
                        throw new Error("Invalid enum value");
                     }
                     element.setAttribute(el.name, obj[el.name].value);
                  }
                  props = props.filter(function(prop) {
                     return prop !== el.name;
                  });
               }
            }
         });
         var base = getBase(objectTypeName);
         if (!isUndefined(base) && isXsdType(base)) {
            element.appendChild(createTextNode(toString(obj.value, base)));
            props.splice(props.indexOf("value"), 1);
         }
         if (!isUndefined(any)) {
            var maxOccurs = any.maxOccurs || objectType.maxOccurs;
            maxOccurs = maxOccurs === "unbounded" ? Infinity : parseInt(maxOccurs);
            if (props.length > maxOccurs) {
               throw new Error("Unnecessary property specified");
            }
            props.forEach(function(key) {
               var objects = Array.isArray(obj[key]) ? obj[key] : [obj[key]];
               objects.forEach(function(obj) {
                  element.appendChild(serializeObject(obj, key));
               });
            });
            props = [];
         }
         if (!isUndefined(anyAttribute)) {
            props.forEach(function(key) {
               element.setAttribute(key, toString(obj[key], getObjectType(obj[key])));
            });
            props = [];
         }
         if (props.length > 0) {
            throw new Error("Unnecessary property specified: " + props[0]);
         }
         return element;
      }

      function deserializeFault(operation, data) {
         var faultElement;
         var type;
         operation.slice(FAULTS_INDEX).forEach(function(element) {
            var fault = getByNameNS(data, getNamespace(element.type).name, element.name)[0];
            if (!isUndefined(fault)) {
               faultElement = fault;
               type = element.type;
            }
         });
         if (isUndefined(faultElement)) {
            var detail = data.getElementsByTagName("detail")[0];
            if (!isUndefined(detail)) {
               faultElement = detail.firstChild;
            }
         }
         var fault = isUndefined(faultElement) ? {} : deserializeObject(type, faultElement);
         if (isUndefined(fault.faultCause)) {
            var faultCodes = data.getElementsByTagName("faultcode")
            var message = faultCodes.length ? faultCodes[0].textContent : 'no fault message'
            fault.faultCause = {
               localizedMessage: message
            };
         }
         if (isUndefined(fault.faultMessage)) {
            var faultMessage = data.getElementsByTagName("faultstring")
            var message = faultMessage.length ? faultMessage[0].textContent : 'no fault message'
            fault.faultMessage = [{
               message: message
            }];
         }
         return fault;
      }

      function deserializeObject(typeName, data) {
         if (isNull(data.textContent)) {
            return undefined;
         }
         var dataType = attr(data, "xsi:type");
         if (dataType) {
            typeName = parseRef(data, dataType, data.namespaceURI);
         }
         if (isXsdType(typeName)) {
            return fromString(data.textContent, typeName);
         } else {
            var ns = getNamespace(typeName);
            var c = getClass(ns, typeName);
            if (!c) {
                console.error('Unknown class found ' + dataType);
                return {};
            }
            var result = new (c)();
            var base = getBase(typeName);
            var type = getType(typeName);
            if (!isUndefined(base) && isXsdType(base)) {
               result.value = fromString(data.textContent, base);
            } else if (!isUndefined(type.enumerations)) {
               result.value = data.textContent;
            }
            getElements(typeName).forEach(function(el) {
               for (var i = 0, j = data.childNodes.length; i !== j; ++i) {
                  if (data.childNodes[i].localName === el.name) {
                     var obj = deserializeObject(el.type, data.childNodes[i]);
                     if (!isUndefined(obj)) {
                        var maxOccurs = el.maxOccurs || type.maxOccurs;
                        if (maxOccurs === "unbounded") {
                           if (Array.isArray(result)) {
                              result.push(obj);
                           } else {
                              if (isUndefined(result[el.name])) {
                                 result[el.name] = [];
                              }
                              result[el.name].push(obj);
                           }
                        } else {
                           result[el.name] = obj;
                        }
                     }
                  }
               }
            });
            getAttributes(typeName).forEach(function(el) {
               for (var i = 0, j = data.attributes.length; i !== j; ++i) {
                  if (data.attributes[i].name === el.name) {
                     if (isXsdType(el.type)) {
                        result[el.name] = fromString(data.attributes[i].value, el.type);
                     } else {
                        var ns = getNamespace(el.type);
                        result[el.name] = new (getClass(ns, el.type))();
                        result[el.name].value = data.attributes[i].value;
                     }
                  }
               }
            });
            return result;
         }
      }

      function getOperationElement(node) {
         var messageName = attr(node, "message").split(":");
         var message = xmlMessages[lookupNamespaceURI(node, messageName[0])][messageName[1]];
         var part = getByNameNS(message, WSDL_NAMESPACE, "part")[0];
         var elementName = attr(part, "element").split(":");
         var element = xmlElements[lookupNamespaceURI(node, elementName[0])][elementName[1]];
         return {
            name: attr(element, "name"),
            type: parseRef(element, attr(element, "type"))
         };
      }

      function findStorageKey() {
         for (var i = 0, key; i !== storage.length; ++i) {
            key = storage.key(i);
            if (key.indexOf(options.serviceName) === 0) {
               return key;
            }
         }
      }

      function processDefinition() {
         namespaces.push({
            name: XSD_NAMESPACE,
            types: [
               "anyType",
               "anyURI",
               "base64Binary",
               "boolean",
               "byte",
               "dateTime",
               "double",
               "float",
               "ID",
               "int",
               "long",
               "negativeInteger",
               "nonNegativeInteger",
               "nonPositiveInteger",
               "positiveInteger",
               "short",
               "string"
            ]
         });
         types.push(namespaces[namespaces.length - 1].types.map(function() {
            return {};
         }));
         keys(xmlTypes).forEach(function(namespace, namespaceIndex) {
            namespaces.push({
               name: namespace,
               types: []
            });
            var types = namespaces[namespaceIndex + 1].types;
            keys(xmlTypes[namespace]).forEach(function(name) {
               types.push(name);
            });
         });
         keys(xmlTypes).forEach(function(namespace, namespaceIndex) {
            types[namespaceIndex + 1] = [];
            keys(xmlTypes[namespace]).forEach(function(name) {
               var elements = [];
               var attributes = [];
               var type = xmlTypes[namespace][name];
               var nodes, subnodes, groupName, i, j, k, l, el, maxOccurs, minOccurs;
               for (i = 0, j = type.childNodes.length; i !== j; ++i) {
                  switch (type.childNodes[i].localName) {
                     case "sequence":
                     case "choice":
                     case "all":
                        maxOccurs = attr(type.childNodes[i], "maxOccurs") || maxOccurs;
                        minOccurs = attr(type.childNodes[i], "minOccurs") || minOccurs;
                  }
               }
               nodes = getByNameNS(type, XSD_NAMESPACE, "element");
               for (i = 0, j = nodes.length; i !== j; ++i) {
                  el = toProperty(nodes[i], xmlElements);
                  if (nodes[i].parentNode.localName === "choice") {
                     el.minOccurs = "0";
                     maxOccurs = attr(nodes[i].parentNode, "maxOccurs") || maxOccurs;
                  }
                  elements.push(el);
               }
               nodes = getByNameNS(type, XSD_NAMESPACE, "any");
               for (i = 0, j = nodes.length; i !== j; ++i) {
                  elements.push(toProperty(nodes[i]));
               }
               nodes = getByNameNS(type, XSD_NAMESPACE, "attribute");
               for (i = 0, j = nodes.length; i !== j; ++i) {
                  attributes.push(toProperty(nodes[i], xmlAttributes));
               }
               nodes = getByNameNS(type, XSD_NAMESPACE, "anyAttribute");
               for (i = 0, j = nodes.length; i !== j; ++i) {
                  attributes.push(toProperty(nodes[i]));
               }
               nodes = getByNameNS(type, XSD_NAMESPACE, "attributeGroup");
               for (i = 0, j = nodes.length, groupName; i !== j; ++i) {
                  groupName = attr(nodes[i], "ref").split(":");
                  var attrGroup = xmlAttributeGroups[
                     lookupNamespaceURI(nodes[i], groupName[0])][groupName[1]];
                  subnodes = getByNameNS(attrGroup, XSD_NAMESPACE, "attribute");
                  for (k = 0, l = subnodes.length; k !== l; ++k) {
                     attributes.push(toProperty(subnodes[k], xmlAttributes));
                  }
                  subnodes = getByNameNS(attrGroup, XSD_NAMESPACE, "anyAttribute");
                  for (k = 0, l = subnodes.length; k !== l; ++k) {
                     attributes.push(toProperty(subnodes[k]));
                  }
               }
               var processedType = {
                  elements: elements,
                  attributes: attributes.length > 0 ? attributes : undefined,
                  maxOccurs: maxOccurs,
                  minOccurs: minOccurs
               };
               var extension = getByNameNS(type, XSD_NAMESPACE, "extension")[0];
               if (!isUndefined(extension)) {
                  processedType.base = parseRef(extension, attr(extension, "base"));
               }
               if (type.localName === "simpleType") {
                  processedType.enumerations = [];
                  nodes = getByNameNS(type, XSD_NAMESPACE, "restriction");
                  for (i = 0, j = nodes.length; i !== j; ++i) {
                     subnodes = getByNameNS(nodes[i], XSD_NAMESPACE, "enumeration");
                     for (k = 0, l = subnodes.length; k !== l; ++k) {
                        processedType.enumerations.push(attr(subnodes[k], "value"));
                     }
                  }
                  processedType.unions = [];
                  nodes = getByNameNS(type, XSD_NAMESPACE, "union");
                  for (i = 0, j = nodes.length; i !== j; ++i) {
                     subnodes = attr(nodes[i], "memberTypes").split(/\s+/g);
                     for (k = 0, l = subnodes.length; k !== l; ++k) {
                        processedType.unions.push(parseRef(nodes[i], subnodes[k]));
                     }
                  }
               }
               types[namespaceIndex + 1].push(processedType);
            });
         });
         keys(xmlOperations).forEach(function(namespace) {
            keys(xmlOperations[namespace]).forEach(function(name) {
               var operation = xmlOperations[namespace][name];
               var input = getOperationElement(getByNameNS(operation, WSDL_NAMESPACE, "input")[0]);
               var output = getOperationElement(getByNameNS(operation, WSDL_NAMESPACE, "output")[0]);
               var faults = [];
               var nodes = getByNameNS(operation, WSDL_NAMESPACE, "fault");
               for (var i = 0, j = nodes.length; i !== j; ++i) {
                  faults.push(getOperationElement(nodes[i]));
               }
               operations[name] = [
                  attr(xmlBindings[namespace][name], "soapAction"),
                  input,
                  output
               ].concat(faults);
            });
         });
         createProperties();
      }

      function processInstance(props) {
         keys(props).forEach(function(name) {
            defineProperty(service, name, {
               value: props[name]
            });
         });
         keys(typeFunctions).forEach(function(namespace) {
            defineProperty(service, options.prefixes[namespace] || namespace, {
               value: typeFunctions[namespace]
            });
         });
         defineProperty(service, options.portName, {
            value: operationFunctions
         });
         defineProperty(service, "addHandler", {
            value: function(handler) {
               handlerChain.add(handler);
            }
         });
         defineProperty(service, "removeHandler", {
            value: function(handler) {
               handlerChain.delete(handler);
            }
         });
         defineProperty(service, "serializeObject", {
            value: serializeObject
         });
         defineProperty(service, "deserializeObject", {
            value: deserializeObject
         });
         return Object.freeze(service);
      }

      function attemptSetStorage(key, obj) {
         try {
            storage.setItem(key, obj);
         } catch (e) {
            for (var i = 0; i !== storage.length; ++i) {
               var storageKey = storage.key(i);
               if (storageKey.indexOf(options.serviceName) === 0) {
                  storage.removeItem(storageKey);
                  attemptSetStorage(key, obj);
                  return;
               }
            }
            console.warn("Could not free enough storage space.");
         }
      }

      function flushStorage() {
         var key = options.storageKey;
         var obj = JSON.stringify({
            operations: operations,
            types: types,
            namespaces: namespaces
         });
         attemptSetStorage(key, obj);
      }

      function processStorage(obj) {
         operations = obj.operations;
         types = obj.types;
         namespaces = obj.namespaces;
         try {
            createProperties();
            return true;
         } catch (e) {
            return false;
         }
      }

      function loadDefinition() {
         return new Promise(function(resolve, reject) {
            operations = {};
            types = [];
            namespaces = [];
            load(options.wsdl, {}, function() {
               processDefinition();
               resolve();
            }, reject);
         });
      }

      function loadFromScratch() {
         memoize.clearCache();
         return loadDefinition().then(function() {
            return options.connect(options, exports);
         }).then(function(props) {
            flushStorage();
            return processInstance(props);
         });
      }

      if (isUndefined(storageKey)) {
         return loadFromScratch();
      } else {
         if (processStorage(JSON.parse(storage.getItem(storageKey)))) {
            return options.connect(options, exports).then(function(props) {
               if (options.storageKey !== storageKey) {
                  return loadFromScratch();
               }
               return processInstance(props);
            });
         } else {
            return loadFromScratch();
         }
      }
   }

   var vsphere = {
      createConverterService: function(hostname, options) {
         return soapService(hostname, merge(defaults, options || {}, {
            connect: function(options, exports) {
               var serviceInstance = new exports.typeFunctions["urn:vim25"].ManagedObjectReference({
                  type: "ConverterServiceInstance",
                  value: "ServiceInstance"
               });
               return exports.operationFunctions.converterRetrieveServiceContent(serviceInstance).then(function(serviceContent) {
                  options.storageKey = options.serviceName + "/" + serviceContent.about.apiVersion;
                  return {
                     serviceContent: serviceContent
                  };
               });
            },
            sdk: "/converter/sdk/",
            wsdl: WSDL_REPO + "/converter/converterService.wsdl",
            serviceName: "ConverterService",
            portName: "converterPort",
            prefixes: {
               "urn:converter": "converter",
               "urn:vim25": "vim"
            }
         }));
      },
      createEamService: function(hostname, options) {
         return soapService(hostname, merge(defaults, options || {}, {
            sdk: "/eam/sdk/",
            wsdl: WSDL_REPO + "/eam/eamService.wsdl",
            serviceName: "EamService",
            portName: "eamPort",
            prefixes: {
               "urn:eam": "eam",
               "urn:vim25": "vim"
            }
         }));
      },
      createIntegrityService: function(hostname, options) {
         return soapService(hostname, merge(defaults, options || {}, {
            sdk: "/integrity/sdk/",
            wsdl: WSDL_REPO + "/integrity/integrityService.wsdl",
            serviceName: "IntergrityService",
            portName: "integrityPort",
            prefixes: {
               "urn:integrity": "integrity",
               "urn:vim25": "vim"
            }
         }));
      },
      createPbmService: function(hostname, options) {
         return soapService(hostname, merge(defaults, options || {}, {
            connect: function(options, exports) {
               var pbmServiceInstance = new exports.typeFunctions["urn:vim25"].ManagedObjectReference({
                  type: "PbmServiceInstance",
                  value: "ServiceInstance"
               });
               return exports.operationFunctions.pbmRetrieveServiceContent(pbmServiceInstance).then(function(pbmServiceContent) {
                  options.storageKey = options.serviceName + "/" + pbmServiceContent.aboutInfo.version;
                  return {
                     pbmServiceContent: pbmServiceContent
                  };
               });
            },
            sdk: "/pbm/sdk/",
            wsdl: WSDL_REPO + "/pbm/pbmService.wsdl",
            serviceName: "PbmService",
            portName: "pbmPort",
            prefixes: {
               "urn:pbm": "pbm",
               "urn:vim25": "vim"
            }
         }));
      },
      createSmsService: function(hostname, options) {
         return soapService(hostname, merge(defaults, options || {}, {
            sdk: "/sms/sdk/",
            wsdl: WSDL_REPO + "/sms/smsService.wsdl",
            serviceName: "SmsService",
            portName: "smsPort",
            prefixes: {
               "urn:sms": "sms",
               "urn:vim25": "vim"
            }
         }));
      },
      createSrmService: function(hostname, options) {
         return soapService(hostname, merge(defaults, options || {}, {
            connect: function(options, exports) {
               var srmServiceInstance = new exports.typeFunctions["urn:vim25"].ManagedObjectReference({
                  type: "SrmServiceInstance",
                  value: "SrmServiceInstance"
               });
               return exports.operationFunctions.retrieveContent(srmServiceInstance).then(function(srmServiceContent) {
                  options.storageKey = options.serviceName + "/" + srmServiceContent.about.version;
                  return {
                     srmServiceContent: srmServiceContent,
                     srmServiceInstance: srmServiceInstance
                  };
               });
            },
            sdk: ":9086/vcdr/extapi/sdk",
            wsdl: ":9086/srm-Service.wsdl",
            serviceName: "SrmService",
            portName: "srmPort",
            prefixes: {
               "urn:srm0": "srm",
               "urn:vim25": "vim"
            }
         }));
      },
      createStsService: function(hostname, options) {
         return soapService(hostname, merge(defaults, options || {}, {
            sdk: "/sts/STSService",
            wsdl: "/sts/STSService?wsdl",
            serviceName: "StsService",
            portName: "stsPort",
            prefixes: {
               "urn:oasis:names:tc:SAML:2.0:conditions:delegation": "del",
               "http://www.w3.org/2000/09/xmldsig#": "ds",
               "http://www.rsa.com/names/2009/12/std-ext/SAML2.0": "smle",
               "http://www.rsa.com/names/2010/04/std-prof/SAML2.0": "smlp",
               "urn:oasis:names:tc:SAML:2.0:assertion": "saml",
               "http://www.w3.org/2005/08/addressing": "wsa",
               "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd": "wsse",
               "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd": "wsu",
               "http://docs.oasis-open.org/ws-sx/ws-trust/200512": "wst13",
               "http://docs.oasis-open.org/ws-sx/ws-trust/200802": "wst14",
               "http://www.rsa.com/names/2009/12/std-ext/WS-Trust1.4/advice": "wsta"
            },
            serialize: function(operation, name, exports, args) {
               var envelope = createDocumentNS(SOAP_NAMESPACE, "Envelope").documentElement;
               var body = envelope.appendChild(
                  createElementNS(SOAP_NAMESPACE, "Body", envelope));
               body.appendChild(exports.serializeObject(args[0],
                  operation[INPUT_INDEX].name, operation[INPUT_INDEX].type));
               return envelope;
            },
            deserialize: function(envelope, operation, name, exports) {
               var outputType = operation[OUTPUT_INDEX].type;
               var node = getByNameNS(envelope, exports.namespaces[outputType[NS_INDEX]].name,
                  operation[OUTPUT_INDEX].name)[0];
               var result = exports.deserializeObject(operation[OUTPUT_INDEX].type, node);
               return result[keys(result)[0]];
            }
         }));
      },
      createVimService: function(hostname, options) {
         return soapService(hostname, merge(defaults, options || {}, {
            connect: function(options, exports) {
               var serviceInstance = new exports.typeFunctions["urn:vim25"].ManagedObjectReference({
                  type: "ServiceInstance",
                  value: "ServiceInstance"
               });
               return exports.operationFunctions.retrieveServiceContent(serviceInstance).then(function(serviceContent) {
                  options.storageKey = options.serviceName + "/" + serviceContent.about.apiVersion + "/" + serviceContent.about.apiType;
                  return {
                     serviceContent: serviceContent
                  };
               });
            },
            sdk: "/sdk/",
            wsdl: "/sdk/vimService.wsdl",
            serviceName: "VimService",
            portName: "vimPort",
            prefixes: {
               "urn:vim25": "vim"
            }
         }));
      },
      createVsanHealthService: function(hostname, options) {
         return soapService(hostname, merge(defaults, options || {}, {
            sdk: "/vsan/",
            wsdl: "/vsan/vsanhealthService.wsdl",
            serviceName: "VsanHealthService",
            portName: "vsanHealthPort",
            prefixes: {
               "urn:vim25": "vim"
            }
         }));
      }
   };

   if (!isUndefined(typeof module) && isObject(module.exports)) {
      if (isUndefined(typeof Map) || isUndefined(typeof Promise) || isUndefined(typeof Object.assign)) {
         require("es6-shim");
      }
      module.exports = vsphere;
   } else if (typeof define === "function" && define.amd) {
      define([], vsphere);
   } else if (!isUndefined(typeof window)) {
      window.vsphere = vsphere;
   } else if (!isUndefined(typeof global)) {
      global.vsphere = vsphere;
   }

})();
