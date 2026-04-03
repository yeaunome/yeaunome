// Probe the TradingView replay trading UI to find buy/sell buttons
import { evaluate } from '../tradingview-mcp/src/connection.js';

async function probe() {
  // Find all buttons in the order panel area
  const buttons = await evaluate(`
    (function() {
      var results = [];
      var btns = document.querySelectorAll('button');
      for (var i = 0; i < btns.length; i++) {
        var b = btns[i];
        var text = (b.textContent || '').trim();
        if (text.length > 0 && text.length < 50 && b.offsetParent !== null) {
          if (/buy|sell|order|market|limit/i.test(text) || /buy|sell/i.test(b.className)) {
            results.push({
              tag: b.tagName,
              cls: (b.className || '').substring(0, 60),
              text: text.substring(0, 40),
              dataName: b.getAttribute('data-name') || '',
              rect: b.getBoundingClientRect().toJSON()
            });
          }
        }
      }
      return results;
    })()
  `);
  console.log('Buy/Sell buttons found:', JSON.stringify(buttons, null, 2));

  // Try clicking the buy button
  const clickResult = await evaluate(`
    (function() {
      var btns = document.querySelectorAll('button');
      for (var i = 0; i < btns.length; i++) {
        var b = btns[i];
        var text = (b.textContent || '').trim();
        // Look for a button that starts with "Buy" or has buy in class
        if (/^Buy/i.test(text) && b.offsetParent !== null) {
          b.click();
          return 'Clicked: ' + text.substring(0, 40);
        }
        if (/buyButton|buy-button|button-buy/i.test(b.className) && b.offsetParent !== null) {
          b.click();
          return 'Clicked by class: ' + b.className.substring(0, 40);
        }
      }
      return 'No buy button found';
    })()
  `);
  console.log('Click result:', clickResult);

  // Check position after click
  await new Promise(r => setTimeout(r, 500));
  const pos = await evaluate(`
    (function() {
      var rp = window.TradingViewApi._replayApi;
      var p = rp.position();
      return p && typeof p.value === 'function' ? p.value() : p;
    })()
  `);
  console.log('Position after click:', pos);
}

probe().catch(e => console.error(e));
