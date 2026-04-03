// Probe TradingView order panel — find Buy/Sell side selectors and place a market buy
import { evaluate } from '../tradingview-mcp/src/connection.js';

async function probe() {
  // Step 1: Find all clickable elements with Buy/Sell text in the order panel
  const elements = await evaluate(`
    (function() {
      var results = [];
      var els = document.querySelectorAll('[class*=order] *, [class*=trading] *');
      for (var i = 0; i < els.length; i++) {
        var e = els[i];
        var text = (e.textContent || '').trim();
        if (text.length > 0 && text.length < 30 && e.offsetParent !== null) {
          if (/^(buy|sell)$/i.test(text) || /buy|sell/i.test(e.className) || /buy|sell/i.test(e.getAttribute('data-name') || '')) {
            results.push({
              tag: e.tagName,
              cls: (e.className || '').substring(0, 80),
              text: text.substring(0, 30),
              dataName: e.getAttribute('data-name') || '',
              children: e.children.length
            });
          }
        }
      }
      return results;
    })()
  `);
  console.log('Buy/Sell elements:', JSON.stringify(elements, null, 2));

  // Step 2: Try to click the "Buy" side selector
  const selectBuy = await evaluate(`
    (function() {
      // Look for elements that say exactly "Buy" with a price
      var all = document.querySelectorAll('[class*=order] *, [class*=trading] *');
      for (var i = 0; i < all.length; i++) {
        var e = all[i];
        var text = (e.textContent || '').trim();
        // Find the Buy side button/div — usually has "Buy" and a price
        if (/^Buy$/i.test(text) && e.offsetParent !== null && e.children.length === 0) {
          e.click();
          return 'Clicked Buy text element: ' + e.tagName + '.' + (e.className || '').substring(0, 40);
        }
      }
      // Try data-name approach
      var buyEl = document.querySelector('[data-name*=buy], [class*=buyButton], [class*=buy-button]');
      if (buyEl) {
        buyEl.click();
        return 'Clicked by selector: ' + buyEl.tagName;
      }
      return 'No Buy element found';
    })()
  `);
  console.log('Select Buy result:', selectBuy);

  // Step 3: Switch to Market order type
  await new Promise(r => setTimeout(r, 300));
  const selectMarket = await evaluate(`
    (function() {
      var tabs = document.querySelectorAll('[class*=underline-tab], [class*=orderType]');
      for (var i = 0; i < tabs.length; i++) {
        if (/^Market$/i.test(tabs[i].textContent.trim())) {
          tabs[i].click();
          return 'Clicked Market tab';
        }
      }
      return 'Market tab not found';
    })()
  `);
  console.log('Market order result:', selectMarket);

  // Step 4: Click "Place order" / "Start creating order"
  await new Promise(r => setTimeout(r, 300));
  const placeOrder = await evaluate(`
    (function() {
      var btn = document.querySelector('[data-name=place-and-modify-button]');
      if (btn) {
        btn.click();
        return 'Clicked: ' + btn.textContent.trim().substring(0, 40);
      }
      return 'Place order button not found';
    })()
  `);
  console.log('Place order result:', placeOrder);

  // Step 5: Check position
  await new Promise(r => setTimeout(r, 1000));
  const pos = await evaluate(`
    (function() {
      var rp = window.TradingViewApi._replayApi;
      var p = rp.position();
      return p && typeof p.value === 'function' ? p.value() : String(p);
    })()
  `);
  console.log('Position after order:', pos);
}

probe().catch(e => console.error(e));
