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

    // Place a Stop order (SL) — used for hard stop loss
    placeStopOrder: function(side, price) {
      var r1 = this.selectSide(side);
      var r2 = this.selectOrderType('Stop');
      var r3 = this.setPrice(price);
      var r4 = this.placeOrder();
      return 'stop|' + r1 + '|' + r2 + '|' + r3 + '|' + r4;
    },

    // Place a Limit order (TP) — used for take profit
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
