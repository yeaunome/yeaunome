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

    // Probe the position bar to find TP/SL buttons and report DOM structure
    probePositionBar: function() {
      var results = [];
      var all = document.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var text = (el.textContent || '').trim();
        // Look for elements containing TP or SL
        if (!/^(TP|SL)$/i.test(text) && text.length > 5) continue;
        if (text.length === 0) continue;
        if (text !== 'TP' && text !== 'SL' && text.length > 4) continue;
        var rect = el.getBoundingClientRect();
        if (rect.width < 5 || rect.height < 5) continue;
        if (rect.left > window.innerWidth * 0.8) continue;
        results.push({
          text: text,
          tag: el.tagName,
          cls: (typeof el.className === 'string' ? el.className.substring(0, 60) : ''),
          id: el.id || '',
          dataName: el.getAttribute('data-name') || '',
          role: el.getAttribute('role') || '',
          w: Math.round(rect.width),
          h: Math.round(rect.height),
          x: Math.round(rect.left),
          y: Math.round(rect.top),
          kids: el.children.length,
          parent: el.parentElement ? el.parentElement.tagName + '.' + (typeof el.parentElement.className === 'string' ? el.parentElement.className.substring(0, 40) : '') : ''
        });
      }
      return JSON.stringify(results);
    },

    // Find the chart canvas and the Y coordinate for a given price
    _getChartCanvas: function() {
      // TradingView renders the chart on a canvas element
      var canvases = document.querySelectorAll('canvas');
      var best = null;
      var bestArea = 0;
      for (var i = 0; i < canvases.length; i++) {
        var c = canvases[i];
        if (!c.offsetParent) continue;
        var rect = c.getBoundingClientRect();
        var area = rect.width * rect.height;
        // The main chart canvas is the largest canvas
        if (area > bestArea && rect.width > 200 && rect.height > 200) {
          bestArea = area;
          best = {canvas: c, rect: rect};
        }
      }
      return best;
    },

    _priceToY: function(price) {
      // Find price labels anywhere on the right side of the screen
      // TradingView renders price axis labels as text in various elements
      var screenW = window.innerWidth;
      var rightEdge = screenW * 0.6; // price labels are on the right portion
      var points = [];

      // Search ALL leaf text nodes for price-like numbers on the right side
      var all = document.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (el.children.length > 0) continue; // leaf only
        if (!el.offsetParent) continue;
        var text = (el.textContent || '').trim().replace(/[,\s]/g, '');
        // Match price-like numbers (4+ digits, optional decimal)
        if (!/^[0-9]{4,}(\.[0-9]+)?$/.test(text)) continue;
        var val = parseFloat(text);
        if (isNaN(val) || val < 1000) continue;
        var r = el.getBoundingClientRect();
        // Must be on the right side of the screen (price axis area)
        if (r.left < rightEdge) continue;
        // Must be reasonable size
        if (r.height < 3 || r.height > 40) continue;
        points.push({price: val, y: r.top + r.height / 2});
      }

      // Also check for canvas-overlay price labels that might be in SVG
      if (points.length < 2) {
        var svgTexts = document.querySelectorAll('text, tspan');
        for (var i = 0; i < svgTexts.length; i++) {
          var el = svgTexts[i];
          var text = (el.textContent || '').trim().replace(/[,\s]/g, '');
          if (!/^[0-9]{4,}(\.[0-9]+)?$/.test(text)) continue;
          var val = parseFloat(text);
          if (isNaN(val) || val < 1000) continue;
          var r = el.getBoundingClientRect();
          if (r.left < rightEdge) continue;
          points.push({price: val, y: r.top + r.height / 2});
        }
      }

      if (points.length < 2) return -1;

      // Deduplicate by Y proximity
      points.sort(function(a, b) { return a.y - b.y; });
      var unique = [points[0]];
      for (var i = 1; i < points.length; i++) {
        if (Math.abs(points[i].y - unique[unique.length - 1].y) > 5) {
          unique.push(points[i]);
        }
      }
      if (unique.length < 2) return -1;

      // Linear interpolation from known price-Y pairs
      var lo = unique[0], hi = unique[unique.length - 1];
      if (hi.price === lo.price) return -1;
      var pxPerPt = (lo.y - hi.y) / (hi.price - lo.price);
      return hi.y + (hi.price - price) * pxPerPt;
    },

    // Debug: report what price labels were found
    _debugPriceLabels: function() {
      var screenW = window.innerWidth;
      var rightEdge = screenW * 0.6;
      var found = [];
      var all = document.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (el.children.length > 0) continue;
        if (!el.offsetParent) continue;
        var text = (el.textContent || '').trim().replace(/[,\s]/g, '');
        if (!/^[0-9]{4,}(\.[0-9]+)?$/.test(text)) continue;
        var r = el.getBoundingClientRect();
        if (r.left < rightEdge) continue;
        if (r.height < 3 || r.height > 40) continue;
        found.push({val: text, x: Math.round(r.left), y: Math.round(r.top), tag: el.tagName});
      }
      return JSON.stringify(found.slice(0, 10));
    },

    // Click on the canvas at specific coordinates (simulates real mouse click)
    _clickCanvas: function(x, y) {
      var chart = this._getChartCanvas();
      if (!chart) return 'no_canvas';
      var el = chart.canvas;
      var opts = {
        clientX: x, clientY: y,
        screenX: x, screenY: y,
        bubbles: true, cancelable: true,
        view: window, detail: 1,
        button: 0, buttons: 1
      };
      el.dispatchEvent(new PointerEvent('pointerdown', opts));
      el.dispatchEvent(new MouseEvent('mousedown', opts));
      el.dispatchEvent(new PointerEvent('pointerup', opts));
      el.dispatchEvent(new MouseEvent('mouseup', opts));
      el.dispatchEvent(new MouseEvent('click', opts));
      return 'canvas_click:' + Math.round(x) + ',' + Math.round(y);
    },

    // Click the TP button on the position bar (canvas-rendered)
    // Position bar layout: [qty ~30px] [TP ~25px] [SL ~25px] [P&L...]
    clickPositionTP: function(entryPrice) {
      var y = this._priceToY(entryPrice);
      if (y < 0) return 'tp_no_y_for_price';
      var chart = this._getChartCanvas();
      if (!chart) return 'tp_no_canvas';
      // TP button is approximately 55-70px from the left edge of the chart
      var x = chart.rect.left + 58;
      return 'tp_' + this._clickCanvas(x, y);
    },

    // Click the SL button on the position bar (canvas-rendered)
    clickPositionSL: function(entryPrice) {
      var y = this._priceToY(entryPrice);
      if (y < 0) return 'sl_no_y_for_price';
      var chart = this._getChartCanvas();
      if (!chart) return 'sl_no_canvas';
      // SL button is approximately 85-100px from the left edge
      var x = chart.rect.left + 92;
      return 'sl_' + this._clickCanvas(x, y);
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

    // Probe ALL visible text in the replay picker area for debugging
    probeAllReplayText: function() {
      var results = [];
      var all = document.querySelectorAll('*');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        if (el.children.length > 2) continue;
        var text = (el.textContent || '').trim();
        if (text.length === 0 || text.length > 50) continue;
        var rect = el.getBoundingClientRect();
        // Only middle area of screen (replay picker)
        if (rect.top < window.innerHeight * 0.2 || rect.top > window.innerHeight * 0.85) continue;
        if (rect.left < window.innerWidth * 0.1 || rect.left > window.innerWidth * 0.9) continue;
        if (rect.width < 5 || rect.height < 5) continue;
        results.push({
          t: text.substring(0, 40),
          tag: el.tagName,
          dn: el.getAttribute('data-name') || '',
          role: el.getAttribute('role') || '',
          cls: (typeof el.className === 'string' ? el.className.substring(0, 50) : ''),
          x: Math.round(rect.left),
          y: Math.round(rect.top),
          w: Math.round(rect.width),
          h: Math.round(rect.height),
          kids: el.children.length,
          clickable: (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button' || el.style.cursor === 'pointer' || !!el.onclick)
        });
      }
      // Deduplicate by text+position
      var seen = {};
      var unique = [];
      for (var j = 0; j < results.length; j++) {
        var key = results[j].t + ':' + results[j].y;
        if (!seen[key]) { seen[key] = true; unique.push(results[j]); }
      }
      return JSON.stringify(unique.slice(0, 25));
    },

    // Click "Random bar" — searches for any element with "Random" text and clicks it.
    // Call this after the SELECT STARTING POINT dropdown is already visible.
    clickRandomBar: function() {
      var all = document.querySelectorAll('*');
      // Pass 1: exact "Random bar" leaf text
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var text = (el.textContent || '').trim();
        if (/^random bar$/i.test(text) && el.children.length === 0) {
          el.click();
          return 'random_bar_clicked:exact_leaf';
        }
      }
      // Pass 2: "Random bar" with up to 2 children (might contain icon + text)
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var text = (el.textContent || '').trim();
        if (/^random bar$/i.test(text) && el.children.length <= 2) {
          el.click();
          return 'random_bar_clicked:exact';
        }
      }
      // Pass 3: contains "Random" anywhere
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var text = (el.textContent || '').trim();
        if (/random/i.test(text) && text.length < 40 && el.children.length <= 3) {
          el.click();
          return 'random_bar_clicked:contains:' + text.substring(0, 30);
        }
      }
      // Pass 4: data-name, aria-label, title containing "random"
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var attrs = (el.getAttribute('data-name') || '') + '|' + (el.getAttribute('aria-label') || '') + '|' + (el.getAttribute('title') || '');
        if (/random/i.test(attrs)) {
          el.click();
          return 'random_bar_clicked:attr:' + attrs.substring(0, 40);
        }
      }
      return 'random_bar_not_found';
    },

    // Open the starting point selector dropdown.
    // Clicks the element that shows the current selection (e.g. "Select first available date")
    openStartingPointDropdown: function() {
      var all = document.querySelectorAll('*');
      // Check if "Random bar" is already visible (dropdown already open)
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var text = (el.textContent || '').trim();
        if (/^random bar$/i.test(text) && el.children.length <= 2) {
          return 'dropdown_already_open';
        }
      }
      // Find and click the starting point selector button/text
      // It shows the current selection like "Select first available date" or "Random bar"
      // Look for elements with these known option texts
      var selectors = [
        /^select first available date$/i,
        /^first available date$/i,
        /^random bar$/i,
        /^date\.\.\.$/i,
        /^bar$/i,
        /select.*starting.*point/i
      ];
      for (var s = 0; s < selectors.length; s++) {
        for (var i = 0; i < all.length; i++) {
          var el = all[i];
          if (!el.offsetParent) continue;
          var text = (el.textContent || '').trim();
          if (selectors[s].test(text) && el.children.length <= 2) {
            var rect = el.getBoundingClientRect();
            // Must be in the bottom half (replay bar area)
            if (rect.top > window.innerHeight * 0.4) {
              el.click();
              return 'dropdown_opened:' + text.substring(0, 30);
            }
          }
        }
      }
      // Look for data-name attributes related to replay starting point
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var dn = el.getAttribute('data-name') || '';
        if (/start|point|date-select|replay-date/i.test(dn)) {
          var rect = el.getBoundingClientRect();
          if (rect.top > window.innerHeight * 0.4) {
            el.click();
            return 'dropdown_opened:dn:' + dn;
          }
        }
      }
      return 'dropdown_not_found';
    },

    // Probe: find all clickable elements in the replay date picker area
    probeReplayPicker: function() {
      var results = [];
      var all = document.querySelectorAll('button, [role=button], [class*=button]');
      for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent) continue;
        var rect = el.getBoundingClientRect();
        // Only elements in the middle of the screen (replay picker area)
        if (rect.top < window.innerHeight * 0.25 || rect.top > window.innerHeight * 0.75) continue;
        if (rect.left < window.innerWidth * 0.1 || rect.left > window.innerWidth * 0.9) continue;
        results.push({
          text: (el.textContent || '').trim().substring(0, 30),
          tag: el.tagName,
          dataName: el.getAttribute('data-name') || '',
          ariaLabel: el.getAttribute('aria-label') || '',
          title: el.getAttribute('title') || '',
          hasSvg: !!el.querySelector('svg'),
          x: Math.round(rect.left),
          y: Math.round(rect.top),
          w: Math.round(rect.width)
        });
      }
      return JSON.stringify(results.slice(0, 15));
    },

    // Cancel all pending orders (limit/stop) by clicking cancel/X buttons
    cancelAllOrders: function() {
      var cancelled = 0;
      // Look for cancel/X buttons on pending orders in the trade list
      // TradingView shows pending orders with a cancel (X) button
      var btns = document.querySelectorAll('button, [class*=cancel], [class*=close], [data-name*=cancel]');
      for (var i = 0; i < btns.length; i++) {
        var btn = btns[i];
        if (!btn.offsetParent) continue;
        var dn = btn.getAttribute('data-name') || '';
        var title = btn.getAttribute('title') || '';
        var ariaLabel = btn.getAttribute('aria-label') || '';
        // Match cancel order buttons
        if (/cancel.*order|remove.*order|delete.*order/i.test(dn + title + ariaLabel)) {
          btn.click();
          cancelled++;
        }
      }
      // Also try: find X buttons near limit/stop order rows
      if (cancelled === 0) {
        var rows = document.querySelectorAll('[class*=order], [class*=pending]');
        for (var i = 0; i < rows.length; i++) {
          var row = rows[i];
          if (!row.offsetParent) continue;
          var text = (row.textContent || '').toLowerCase();
          if (/limit|stop/i.test(text)) {
            var xBtns = row.querySelectorAll('button, [class*=cancel], [class*=close]');
            for (var j = 0; j < xBtns.length; j++) {
              if (xBtns[j].offsetParent) {
                xBtns[j].click();
                cancelled++;
              }
            }
          }
        }
      }
      return 'cancelled:' + cancelled;
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
