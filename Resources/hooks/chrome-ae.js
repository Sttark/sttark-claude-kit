// Shared by claude-window.sh and profile-sync.py: Apple events to one Chrome process by its id.
ObjC.import('Foundation')
// Apple events sent to one process by its id, built by hand: "tell application" and JXA's Application() pick
// a copy of Chrome by name, which can be a test tool's copy.
var D = $.NSAppleEventDescriptor, PID = 0
function fc(s) { return ((s.charCodeAt(0) << 24) | (s.charCodeAt(1) << 16) | (s.charCodeAt(2) << 8) | s.charCodeAt(3)) >>> 0 }
function str(s) { return D.descriptorWithString(s) }
function obj(want, from, form, data) {
  var r = D.recordDescriptor
  r.setDescriptorForKeyword(D.descriptorWithTypeCode(fc(want)), fc('want'))
  r.setDescriptorForKeyword(from || D.nullDescriptor, fc('from'))
  r.setDescriptorForKeyword(D.descriptorWithEnumCode(fc(form)), fc('form'))
  r.setDescriptorForKeyword(data, fc('seld'))
  return r.coerceToDescriptorType(fc('obj '))
}
function nth(want, from, i) { return obj(want, from, 'indx', D.descriptorWithInt32(i)) }
function prop(code, from) { return obj('prop', from, 'prop', D.descriptorWithTypeCode(fc(code))) }
function send(cls, id, params) {
  var e = D.appleEventWithEventClassEventIDTargetDescriptorReturnIDTransactionID(fc(cls), fc(id),
    D.descriptorWithProcessIdentifier(PID), -1, 0)
  Object.keys(params || {}).forEach(function (k) { e.setParamDescriptorForKeyword(params[k], fc(k)) })
  var err = Ref()
  var reply = e.sendEventWithOptionsTimeoutError(0x3 /* wait for reply */, 120, err)
  if (reply.isNil()) throw new Error(ObjC.unwrap(err[0].localizedDescription) + ' (' + err[0].code + ')')
  var n = reply.paramDescriptorForKeyword(fc('errn'))
  if (!n.isNil() && n.int32Value !== 0) {
    var m = reply.paramDescriptorForKeyword(fc('errs'))
    throw new Error((m.isNil() ? 'Chrome error' : ObjC.unwrap(m.stringValue)) + ' (' + n.int32Value + ')')
  }
  return reply.paramDescriptorForKeyword(fc('----'))
}
function val(d) {  // a reply as a plain value
  if (d.isNil()) return undefined
  var t = d.descriptorType
  if (t === fc('list')) { var a = []; for (var i = 1; i <= d.numberOfItems; i++) a.push(val(d.descriptorAtIndex(i))); return a }
  if (t === fc('reco')) {
    var o = {}, u = d.descriptorForKeyword(fc('usrf'))
    if (!u.isNil()) for (var j = 1; j < u.numberOfItems; j += 2) o[ObjC.unwrap(u.descriptorAtIndex(j).stringValue)] = val(u.descriptorAtIndex(j + 1))
    return o
  }
  if (t === fc('type') && d.typeCodeValue === fc('msng')) return null
  if (t === fc('true')) return true
  if (t === fc('fals')) return false
  if (t === fc('bool')) return d.booleanValue
  if (t === fc('long') || t === fc('shor')) return d.int32Value
  if (t === fc('doub') || t === fc('sing')) return d.doubleValue
  var s = d.stringValue
  return s.isNil() ? undefined : ObjC.unwrap(s)
}
function every(cls, from) {
  return obj(cls, from, 'indx', D.descriptorWithDescriptorTypeData(fc('abso'), D.descriptorWithTypeCode(fc('all ')).data))
}
function get(spec) { return val(send('core', 'getd', {'----': spec})) }
function count(cls, from) { return val(send('core', 'cnte', {'----': from || D.nullDescriptor, kocl: D.descriptorWithTypeCode(fc(cls))})) }
function set(spec, v) { send('core', 'setd', {'----': spec, data: v}) }
function make(cls, at) {
  var p = {kocl: D.descriptorWithTypeCode(fc(cls))}
  if (at) {
    var l = D.recordDescriptor
    l.setDescriptorForKeyword(at, fc('kobj'))
    l.setDescriptorForKeyword(D.descriptorWithEnumCode(fc('end ')), fc('kpos'))
    p.insh = l.coerceToDescriptorType(fc('insl'))
  }
  return send('core', 'crel', p)
}
function claudeWindow() {  // the window named Claude, or null
  var names = get(prop('GNam', every('cwin'))) || [], i = names.indexOf('Claude')
  return i < 0 ? null : obj('cwin', null, 'ID  ', D.descriptorWithInt32(get(prop('ID  ', nth('cwin', null, i + 1)))))
}
