/**
 * Trade helper for Floopbot — DOM-based trade execution in TradingView replay.
 * Loaded via: node tradingview-mcp/src/cli/index.js ui eval "<short bootstrap>"
 * Then called via: window._floop.buy(), window._floop.sell(), etc.
 */

// This file is evaluated directly via CDP Runtime.evaluate
// It installs window._floop with trade helper methods.

(function() {
  window._floop = {
    // Click the "Trade" tab at the bottom-left (next to "Replay Trading")
    openTradePanel: function() {
      // Check if order panel with Sell/Buy is actually visible (width > 50)
      var panel = document.querySelector('[class*=orderWidget], [class*=orderTicket], [class*=orderPanel]');
      if (panel && panel.offsetParent && panel.offsetWidth > 50) {
        var text = panel.textContent || '';
        if (/Sell.*Buy|Buy.*Sell/i.test(text)) return 'already_open';
      }
      // Find a leaf SPAN with text exactly "Trade" (the bottom tab)
      var spans = document.querySelectorAll('span');
      for (var i = 0; i < spans.length; i++) {
        var el = spans[i];
        if (!el.offsetParent) continue;
        if (el.children.length > 0) continue;
        if (el.textContent.trim() === 'Trade') {
          // Verify it's in the bottom half of the page (not the top Trade button)
          var rect = el.getBoundingClientRect();
          if (rect.top > window.innerHeight * 0.5) {
            el.click();
            return 'trade_tab_clicked';
          }
        }
      }
      // Fallback: click any "Trade" span regardless of position
      for (var i = 0; i < spans.length; i++) {
        var el = spans[i];
        if (!el.offsetParent) continue;
        if (el.children.length > 0) continue;
        if (el.textContent.trim() === 'Trade') {
          el.click();
          return 'trade_tab_clicked_fallback';
        }
      }
      return 'trade_tab_not_found';
    },

    // Select Buy or Sell side in the order panel
    selectSide: function(side) {
      // Look in the right-side trading panel area
      var panel = document.querySelector('[class*=tradingpanel], [class*=orderWidget], [class*=orderTicket], [class*=orderPanel]');
      var searchIn = panel || document;
      var els = searchIn.querySelectorAll('span, div, button, a');
      for (var i = 0; i < els.length; i++) {
        var e = els[i];
        if (!e.offsetParent) continue;
        var text = (e.textContent || '').trim();
        // Match exact "Buy" or "Sell" with no children (leaf text node)
        if (new RegExp('^' + side + '$', 'i').test(text) && e.children.length === 0) {
          e.click();
          return 'selected_' + side;
        }
      }
      // Second pass: match "Buy" or "Sell" followed by price like "Buy15,159.75"
      for (var i = 0; i < els.length; i++) {
        var e = els[i];
        if (!e.offsetParent) continue;
        var text = (e.textContent || '').trim();
        if (new RegExp('^' + side + '[\\s0-9,.]', 'i').test(text) && e.children.length <= 3) {
          e.click();
          return 'selected_' + side + '_price';
        }
      }
      return 'not_found_' + side;
    },

    // Set the quantity/units in the order panel
    setQuantity: function(qty) {
      var panel = document.querySelector('[class*=orderWidget], [class*=orderTicket], [class*=orderPanel]');
      var searchIn = panel || document;
      var inputs = searchIn.querySelectorAll('input');
      var target = null;

      // Strategy 1: Find input near "Units" label
      for (var i = 0; i < inputs.length; i++) {
        var inp = inputs[i];
        if (!inp.offsetParent) continue;
        // Walk up to find "Units" text nearby
        var el = inp;
        for (var depth = 0; depth < 5 && el; depth++) {
          el = el.parentElement;
          if (el && /\bUnits\b/i.test(el.textContent || '')) {
            target = inp;
            break;
          }
        }
        if (target) break;
      }

      // Strategy 2: Find input with small integer (1-99) that's NOT a price
      if (!target) {
        for (var i = 0; i < inputs.length; i++) {
          var inp = inputs[i];
          if (!inp.offsetParent) continue;
          var val = inp.value || '';
          var num = parseInt(val);
          if (num > 0 && num < 100 && val.indexOf('.') === -1) {
            target = inp;
            break;
          }
        }
      }

      if (!target) return 'qty_input_not_found';

      // Focus, select all, then simulate keystrokes to set value
      target.focus();
      target.select();
      // Clear existing value
      target.dispatchEvent(new KeyboardEvent('keydown', {key: 'a', code: 'KeyA', ctrlKey: true, bubbles: true}));

      // Use native setter + multiple event types for React compatibility
      var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSet.call(target, String(qty));
      target.dispatchEvent(new Event('input', {bubbles: true}));
      target.dispatchEvent(new Event('change', {bubbles: true}));

      // Also try React's synthetic event approach
      var tracker = target._valueTracker;
      if (tracker) { tracker.setValue(''); }
      target.value = String(qty);
      target.dispatchEvent(new Event('input', {bubbles: true}));

      // Blur to confirm
      target.dispatchEvent(new Event('blur', {bubbles: true}));
      return 'qty_set_' + qty + '_was_' + (target.value);
    },

    // Click Market order type
    selectMarket: function() {
      var tabs = document.querySelectorAll('button, [class*=tab]');
      for (var i = 0; i < tabs.length; i++) {
        if (/^Market$/i.test(tabs[i].textContent.trim()) && tabs[i].offsetParent) {
          tabs[i].click();
          return 'market_selected';
        }
      }
      return 'market_not_found';
    },

    // Click Place Order button (the big "Buy 5 MNQ1! MARKET" button)
    placeOrder: function() {
      // Try data-name first
      var btn = document.querySelector('[data-name=place-and-modify-button]');
      if (btn && btn.offsetParent) {
        btn.click();
        return 'order_placed';
      }
      // Fallback: find button with "MARKET" text in the trading panel
      var btns = document.querySelectorAll('button');
      for (var i = 0; i < btns.length; i++) {
        var text = (btns[i].textContent || '').trim();
        if (/MARKET/i.test(text) && /Buy|Sell/i.test(text) && btns[i].offsetParent) {
          btns[i].click();
          return 'order_placed_market_btn';
        }
      }
      // Try "Start creating order" button
      for (var i = 0; i < btns.length; i++) {
        var text = (btns[i].textContent || '').trim();
        if (/start creating|place order|submit/i.test(text) && btns[i].offsetParent) {
          btns[i].click();
          return 'order_placed_submit';
        }
      }
      return 'place_button_not_found';
    },

    // Full buy flow
    buy: function() {
      var r1 = this.openTradePanel();
      if (r1 === 'trade_tab_not_found' || r1 === 'no_bottom_bar') return 'fail:' + r1;
      if (r1 === 'trade_tab_clicked') { /* wait handled by caller */ }
      var r2 = this.selectSide('Buy');
      if (r2.indexOf('not_found') >= 0) return 'fail:' + r2;
      var r3 = this.selectMarket();
      var r4 = this.placeOrder();
      return r1 + '|' + r2 + '|' + r3 + '|' + r4;
    },

    // Full sell flow
    sell: function() {
      var r1 = this.openTradePanel();
      if (r1 === 'trade_tab_not_found' || r1 === 'no_bottom_bar') return 'fail:' + r1;
      var r2 = this.selectSide('Sell');
      if (r2.indexOf('not_found') >= 0) return 'fail:' + r2;
      var r3 = this.selectMarket();
      var r4 = this.placeOrder();
      return r1 + '|' + r2 + '|' + r3 + '|' + r4;
    },

    // Close position
    close: function() {
      var btns = document.querySelectorAll('button, [class*=close], [class*=flatten]');
      for (var i = 0; i < btns.length; i++) {
        var text = (btns[i].textContent || '').trim();
        if (/^close|^flatten|close position/i.test(text) && btns[i].offsetParent) {
          btns[i].click();
          return 'closed';
        }
      }
      // Fallback: API close
      try { window.TradingViewApi._replayApi.closePosition(); } catch(e) {}
      return 'api_close';
    },

    // Select order type tab (Market, Limit, Stop, Stop Limit)
    selectOrderType: function(type) {
      var tabs = document.querySelectorAll('button, [class*=tab], [role=tab]');
      for (var i = 0; i < tabs.length; i++) {
        var text = tabs[i].textContent.trim();
        if (text === type && tabs[i].offsetParent) {
          tabs[i].click();
          return 'selected_' + type;
        }
      }
      // Fuzzy match
      for (var i = 0; i < tabs.length; i++) {
        var text = tabs[i].textContent.trim();
        if (new RegExp('^' + type + '$', 'i').test(text) && tabs[i].offsetParent) {
          tabs[i].click();
          return 'selected_' + type + '_fuzzy';
        }
      }
      return 'not_found_' + type;
    },

    // Set price in the order price input field
    setPrice: function(price) {
      // Find the price input in the order panel — look for input near "Price" label
      var panel = document.querySelector('[class*=orderWidget], [class*=orderTicket], [class*=orderPanel]');
      var searchIn = panel || document;
      var inputs = searchIn.querySelectorAll('input[type=text], input[type=number], input:not([type])');
      var priceInput = null;

      for (var i = 0; i < inputs.length; i++) {
        var inp = inputs[i];
        if (!inp.offsetParent) continue;
        // Skip the units/quantity field (usually has small integer values)
        var val = inp.value || '';
        if (/^[0-9]{1,3}$/.test(val) && parseFloat(val) < 100) continue;
        // Look for input near a "Price" or "Stop" label
        var parent = inp.closest('[class*=row], [class*=field], [class*=group]') || inp.parentElement;
        var parentText = (parent && parent.textContent) || '';
        if (/price|stop price|limit price/i.test(parentText)) {
          priceInput = inp;
          break;
        }
      }

      // Fallback: find input with a value that looks like a price (4+ digits)
      if (!priceInput) {
        for (var i = 0; i < inputs.length; i++) {
          var inp = inputs[i];
          if (!inp.offsetParent) continue;
          var val = inp.value || '';
          if (/^[0-9]{4,}/.test(val.replace(/[,.]/g, ''))) {
            priceInput = inp;
            break;
          }
        }
      }

      if (!priceInput) return 'price_input_not_found';

      // Set the value using React-compatible method
      var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSet.call(priceInput, String(price));
      priceInput.dispatchEvent(new Event('input', {bubbles: true}));
      priceInput.dispatchEvent(new Event('change', {bubbles: true}));
      // Also try blur to confirm
      priceInput.dispatchEvent(new Event('blur', {bubbles: true}));
      return 'price_set_' + price;
    },

    // Click the TP button on the position bar (appears after entering a trade)
    clickPositionTP: function() {
      return this._clickPositionButton('TP');
    },

    // Click the SL button on the position bar
    clickPositionSL: function() {
      return this._clickPositionButton('SL');
    },

    // Generic: find and click a button on the chart position bar
    _clickPositionButton: function(label) {
      // Strategy 1: Search ALL visible elements for exact text match
      var all = document.querySelectorAll('*');
      var candidates = [];
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        // Must be leaf or near-leaf with exact text
        var text = el.textContent.trim();
        if (text !== label) continue;
        // Prefer elements with no children or only text children
        if (el.children.length > 2) continue;
        var rect = el.getBoundingClientRect();
        // Must be on the chart (not in sidepanel), not too small
        if (rect.width < 10 || rect.height < 10) continue;
        if (rect.left > window.innerWidth * 0.75) continue; // not in order panel
        candidates.push({el: el, rect: rect, tag: el.tagName, cls: el.className});
      }
      if (candidates.length === 0) return label.toLowerCase() + '_not_found_0_candidates';

      // Click the best candidate — prefer ones with smaller bounding box (more specific)
      candidates.sort(function(a, b) {
        return (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height);
      });
      var best = candidates[0];
      best.el.click();
      return label.toLowerCase() + '_clicked:' + best.tag + ':' + (typeof best.cls === 'string' ? best.cls.substring(0, 30) : '');
    },

    // Set the price on a TP/SL input that appears after clicking TP or SL
    setTPSLPrice: function(price) {
      // After clicking TP or SL, TradingView shows a price input on the chart
      // It could be an input field, or an editable element
      var inputs = document.querySelectorAll('input');
      var candidates = [];

      for (var i = 0; i < inputs.length; i++) {
        var inp = inputs[i];
        if (!inp.offsetParent) continue;
        var rect = inp.getBoundingClientRect();
        // Must be on the chart area (not in the order panel on the right)
        if (rect.left > window.innerWidth * 0.75) continue;
        var val = inp.value || '';
        candidates.push({inp: inp, val: val, rect: rect});
      }

      if (candidates.length === 0) return 'tpsl_input_not_found:0_inputs_on_chart';

      // Pick the most recently appeared / most relevant input
      // Prefer inputs with price-like values, or empty inputs ready for input
      var best = null;
      for (var j = 0; j < candidates.length; j++) {
        var c = candidates[j];
        if (/^[0-9]{2,}/.test(c.val.replace(/[,.]/g, ''))) {
          best = c.inp;
          break;
        }
      }
      // Fallback: any input on chart area
      if (!best) best = candidates[0].inp;

      // Focus and select all existing text
      best.focus();
      best.select();

      // Use React-compatible value setting
      var tracker = best._valueTracker;
      if (tracker) tracker.setValue('');
      var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeSet.call(best, String(price));
      best.dispatchEvent(new Event('input', {bubbles: true}));
      best.dispatchEvent(new Event('change', {bubbles: true}));

      // Press Enter to confirm the price
      best.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
      best.dispatchEvent(new KeyboardEvent('keypress', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
      best.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));

      return 'tpsl_price_set_' + price + '_was_' + (best.value);
    },

    // Legacy: Place a Stop order via order panel tabs (fallback)
    placeStopOrder: function(side, price) {
      var r1 = this.selectSide(side);
      var r2 = this.selectOrderType('Stop');
      var r3 = this.setPrice(price);
      var r4 = this.placeOrder();
      return 'stop|' + r1 + '|' + r2 + '|' + r3 + '|' + r4;
    },

    // Legacy: Place a Limit order via order panel tabs (fallback)
    placeLimitOrder: function(side, price) {
      var r1 = this.selectSide(side);
      var r2 = this.selectOrderType('Limit');
      var r3 = this.setPrice(price);
      var r4 = this.placeOrder();
      return 'limit|' + r1 + '|' + r2 + '|' + r3 + '|' + r4;
    },

    // Switch back to Market order type after placing stop/limit
    resetToMarket: function() {
      return this.selectOrderType('Market');
    },

    // Step 1: Click the step interval button to open its dropdown/menu
    openStepMenu: function() {
      // The replay bar has: play/pause, step, step-forward, 1x speed, "5m" step size, skip-to-end
      // The "5m" is a clickable button/span in the bottom replay controls area
      var all = document.querySelectorAll('button, span, div');
      var candidates = [];
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var text = el.textContent.trim();
        // Match step sizes: "1s","5s","10s","30s","1m","3m","5m","15m","30m","1h" etc.
        if (/^[0-9]+[smh]$/.test(text) && el.children.length === 0) {
          var rect = el.getBoundingClientRect();
          // Must be in the bottom area of the screen (replay controls)
          if (rect.top > window.innerHeight * 0.65) {
            candidates.push({el: el, text: text, top: rect.top, tag: el.tagName});
          }
        }
      }
      if (candidates.length === 0) return 'step_btn_not_found';
      // Click the best candidate (rightmost in the replay bar area)
      var best = candidates[candidates.length - 1];
      best.el.click();
      return 'step_menu_opened:' + best.text + ':' + best.tag;
    },

    // Step 2: Select an interval from the open dropdown/menu
    selectStepInterval: function(interval) {
      // After openStepMenu(), a dropdown/popup should be visible
      // Search for the target interval text in visible elements
      var all = document.querySelectorAll('span, div, [class*=item], [role=option], [role=menuitem]');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var text = el.textContent.trim();
        if (text === interval && el.children.length === 0) {
          el.click();
          return 'interval_selected:' + interval;
        }
      }
      // Try with case-insensitive match
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var text = el.textContent.trim();
        if (text.toLowerCase() === interval.toLowerCase() && el.children.length <= 1) {
          el.click();
          return 'interval_selected_fuzzy:' + interval;
        }
      }
      return 'interval_not_found:' + interval;
    },

    // Dismiss dialogs (Stay on "Leave current replay?")
    dismissDialog: function() {
      var btns = document.querySelectorAll('button');
      for (var i = 0; i < btns.length; i++) {
        if (/^Stay$/i.test(btns[i].textContent.trim()) && btns[i].offsetParent) {
          btns[i].click();
          return 'stayed';
        }
      }
      return 'no_dialog';
    }
  };
  return 'floop_helper_installed';
})();
