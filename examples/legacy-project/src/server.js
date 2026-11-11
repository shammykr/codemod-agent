// Legacy inventory UI helpers (Node 0.12 era).
var util = require('util');
var url = require('url');

function parseQuery(href) {
  var parsed = url.parse(href, true);
  return parsed.query;
}

function encodeToken(user) {
  var buf = new Buffer(user + ':' + Date.now());
  return buf.toString('base64');
}

function countItems(items) {
  if (!util.isArray(items)) {
    return 0;
  }
  var total = 0;
  for (var i = 0; i < items.length; i++) {
    if (items[i].qty != null) {
      total += items[i].qty;
    }
  }
  return total;
}

function describe(count) {
  var label = 'items';
  if (count == 1) {
    var label = 'item';
  }
  return count + ' ' + label;
}

console.log(parseQuery('http://shop.local/search?q=bolt').q);
console.log(encodeToken('admin').length > 0);
console.log(describe(countItems([{ qty: 2 }, { qty: 3 }])));
if (describe(1) !== '1 item') {
  throw new Error('describe() regression');
}
