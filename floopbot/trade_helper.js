/**
 * Trade helper for Floopbot — DOM-based trade execution in TradingView replay.
 * Loaded via: node tradingview-mcp/src/cli/index.js ui eval "<short bootstrap>"
 * Then called via: window._floop.buy(), window._floop.sell(), etc.
 */

// This file is evaluated directly via CDP Runtime.evaluate
// It installs window._floop with trade helper methods.

(function() {
  window._floop = {
    // Click the Trade tab in the bottom bar
    openTradePanel: function() {
      // Check if order panel is already open
      var op = document.querySelector('[class*=orderWidget], [class*=orderTicket], [class*=orderPanel]');
      if (op && op.offsetParent) return 'already_open';
      // Find Trade tab in bottom bar only
      var bottom = document.querySelector('[class*=bottom-widgetbar], [class*="layout__area--bottom"]');
      if (!bottom) return 'no_bottom_bar';
      var tabs = bottom.querySelectorAll('button, [class*=tab], [role=tab]');
      for (var i = 0; i < tabs.length; i++) {
        if (/^Trade$/i.test(tabs[i].textContent.trim()) && tabs[i].offsetParent) {
          tabs[i].click();
          return 'trade_tab_clicked';
        }
      }
      return 'trade_tab_not_found';
    },

    // Select Buy or Sell side in the order panel
    selectSide: function(side) {
      var containers = document.querySelectorAll('[class*=order], [class*=trading], [class*=ticket]');
      for (var c = 0; c < containers.length; c++) {
        var els = containers[c].querySelectorAll('span, div, button, a');
        for (var i = 0; i < els.length; i++) {
          var e = els[i];
          if (!e.offsetParent) continue;
          var text = (e.textContent || '').trim();
          if (new RegExp('^' + side + '$', 'i').test(text) && e.children.length === 0) {
            e.click();
            return 'selected_' + side;
          }
          if (new RegExp('^' + side + '[0-9,. ]', 'i').test(text) && e.children.length <= 2) {
            e.click();
            return 'selected_' + side + '_with_price';
          }
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

    // Click Place Order button
    placeOrder: function() {
      var btn = document.querySelector('[data-name=place-and-modify-button]');
      if (btn && btn.offsetParent) {
        btn.click();
        return 'order_placed';
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
