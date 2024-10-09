/*

Quicksand 1.2.2

Reorder and filter items with a nice shuffling animation.

Copyright (c) 2010 Jacek Galanciak (razorjack.net) and agilope.com
Big thanks for Piotr Petrus (riddle.pl) for deep code review and wonderful docs & demos.

Dual licensed under the MIT and GPL version 2 licenses.
http://github.com/jquery/jquery/blob/master/MIT-LICENSE.txt
http://github.com/jquery/jquery/blob/master/GPL-LICENSE.txt

Project site: http://razorjack.net/quicksand
Github site: http://github.com/razorjack/quicksand

*/

(function ($) {
  $.fn.quicksand = function (collection, customOptions) {
    var options = {
      duration: 750,
      easing: "swing",
      attribute: "data-id", // attribute to recognize same items within source and dest
      adjustHeight: "auto", // 'dynamic' animates height during shuffling (slow), 'auto' adjusts it before or after the animation, false leaves height constant
      useScaling: true, // disable it if you're not using scaling effect or want to improve performance
      enhancement: function (c) {}, // Visual enhacement (eg. font replacement) function for cloned elements
      selector: "> *",
      dx: 0,
      dy: 0,
    };
    $.extend(options, customOptions);

    if ($.browser.msie || typeof $.fn.scale == "undefined") {
      // Got IE and want scaling effect? Kiss my ass.
      options.useScaling = false;
    }

    var callbackFunction;
    if (typeof arguments[1] == "function") {
      var callbackFunction = arguments[1];
    } else if (typeof (arguments[2] == "function")) {
      var callbackFunction = arguments[2];
    }

    return this.each(function (i) {
      var val;
      var animationQueue = []; // used to store all the animation params before starting the animation; solves initial animation slowdowns
      var $collection = $(collection).clone(); // destination (target) collection
      var $sourceParent = $(this); // source, the visible container of source collection
      var sourceHeight = $(this).css("height"); // used to keep height and document flow during the animation

      var destHeight;
      var adjustHeightOnCallback = false;

      var offset = $($sourceParent).offset(); // offset of visible container, used in animation calculations
      var offsets = []; // coordinates of every source collection item

      var $source = $(this).find(options.selector); // source collection items

      // Replace the collection and quit if IE6
      if ($.browser.msie && $.browser.version.substr(0, 1) < 7) {
        $sourceParent.html("").append($collection);
        return;
      }

      // Gets called when any animation is finished
      var postCallbackPerformed = 0; // prevents the function from being called more than one time
      var postCallback = function () {
        if (!postCallbackPerformed) {
          postCallbackPerformed = 1;

          // hack:
          // used to be: $sourceParent.html($dest.html()); // put target HTML into visible source container
          // but new webkit builds cause flickering when replacing the collections
          $toDelete = $sourceParent.find("> *");
          $sourceParent.prepend($dest.find("> *"));
          $toDelete.remove();

          if (adjustHeightOnCallback) {
            $sourceParent.css("height", destHeight);
          }
          options.enhancement($sourceParent); // Perform custom visual enhancements on a newly replaced collection
          if (typeof callbackFunction == "function") {
            callbackFunction.call(this);
          }
        }
      };

      // Position: relative situations
      var $correctionParent = $sourceParent.offsetParent();
      var correctionOffset = $correctionParent.offset();
      if ($correctionParent.css("position") == "relative") {
        if ($correctionParent.get(0).nodeName.toLowerCase() == "body") {
        } else {
          correctionOffset.top +=
            parseFloat($correctionParent.css("border-top-width")) || 0;
          correctionOffset.left +=
            parseFloat($correctionParent.css("border-left-width")) || 0;
        }
      } else {
        correctionOffset.top -=
          parseFloat($correctionParent.css("border-top-width")) || 0;
        correctionOffset.left -=
          parseFloat($correctionParent.css("border-left-width")) || 0;
        correctionOffset.top -=
          parseFloat($correctionParent.css("margin-top")) || 0;
        correctionOffset.left -=
          parseFloat($correctionParent.css("margin-left")) || 0;
      }

      // perform custom corrections from options (use when Quicksand fails to detect proper correction)
      if (isNaN(correctionOffset.left)) {
        correctionOffset.left = 0;
      }
      if (isNaN(correctionOffset.top)) {
        correctionOffset.top = 0;
      }

      correctionOffset.left -= options.dx;
      correctionOffset.top -= options.dy;

      // keeps nodes after source container, holding their position
      $sourceParent.css("height", $(this).height());

      // get positions of source collections
      $source.each(function (i) {
        offsets[i] = $(this).offset();
      });

      // stops previous animations on source container
      $(this).stop();
      var dx = 0;
      var dy = 0;
      $source.each(function (i) {
        $(this).stop(); // stop animation of collection items
        var rawObj = $(this).get(0);
        if (rawObj.style.position == "absolute") {
          dx = -options.dx;
          dy = -options.dy;
        } else {
          dx = options.dx;
          dy = options.dy;
        }

        rawObj.style.position = "absolute";
        rawObj.style.margin = "0";

        rawObj.style.top =
          offsets[i].top -
          parseFloat(rawObj.style.marginTop) -
          correctionOffset.top +
          dy +
          "px";
        rawObj.style.left =
          offsets[i].left -
          parseFloat(rawObj.style.marginLeft) -
          correctionOffset.left +
          dx +
          "px";
      });

      // create temporary container with destination collection
      var $dest = $($sourceParent).clone();
      var rawDest = $dest.get(0);
      rawDest.innerHTML = "";
      rawDest.setAttribute("id", "");
      rawDest.style.height = "auto";
      rawDest.style.width = $sourceParent.width() + "px";
      $dest.append($collection);
      // insert node into HTML
      // Note that the node is under visible source container in the exactly same position
      // The browser render all the items without showing them (opacity: 0.0)
      // No offset calculations are needed, the browser just extracts position from underlayered destination items
      // and sets animation to destination positions.
      $dest.insertBefore($sourceParent);
      $dest.css("opacity", 0.0);
      rawDest.style.zIndex = -1;

      rawDest.style.margin = "0";
      rawDest.style.position = "absolute";
      rawDest.style.top = offset.top - correctionOffset.top + "px";
      rawDest.style.left = offset.left - correctionOffset.left + "px";

      if (options.adjustHeight === "dynamic") {
        // If destination container has different height than source container
        // the height can be animated, adjusting it to destination height
        $sourceParent.animate(
          { height: $dest.height() },
          options.duration,
          options.easing,
        );
      } else if (options.adjustHeight === "auto") {
        destHeight = $dest.height();
        if (parseFloat(sourceHeight) < parseFloat(destHeight)) {
          // Adjust the height now so that the items don't move out of the container
          $sourceParent.css("height", destHeight);
        } else {
          //  Adjust later, on callback
          adjustHeightOnCallback = true;
        }
      }

      // Now it's time to do shuffling animation
      // First of all, we need to identify same elements within source and destination collections
      $source.each(function (i) {
        var destElement = [];
        if (typeof options.attribute == "function") {
          val = options.attribute($(this));
          $collection.each(function () {
            if (options.attribute(this) == val) {
              destElement = $(this);
              return false;
            }
          });
        } else {
          destElement = $collection.filter(
            "[" +
              options.attribute +
              "=" +
              $(this).attr(options.attribute) +
              "]",
          );
        }
        if (destElement.length) {
          // The item is both in source and destination collections
          // It it's under different position, let's move it
          if (!options.useScaling) {
            animationQueue.push({
              element: $(this),
              animation: {
                top: destElement.offset().top - correctionOffset.top,
                left: destElement.offset().left - correctionOffset.left,
                opacity: 1.0,
              },
            });
          } else {
            animationQueue.push({
              element: $(this),
              animation: {
                top: destElement.offset().top - correctionOffset.top,
                left: destElement.offset().left - correctionOffset.left,
                opacity: 1.0,
                scale: "1.0",
              },
            });
          }
        } else {
          // The item from source collection is not present in destination collections
          // Let's remove it
          if (!options.useScaling) {
            animationQueue.push({
              element: $(this),
              animation: { opacity: "0.0" },
            });
          } else {
            animationQueue.push({
              element: $(this),
              animation: { opacity: "0.0", scale: "0.0" },
            });
          }
        }
      });

      $collection.each(function (i) {
        // Grab all items from target collection not present in visible source collection

        var sourceElement = [];
        var destElement = [];
        if (typeof options.attribute == "function") {
          val = options.attribute($(this));
          $source.each(function () {
            if (options.attribute(this) == val) {
              sourceElement = $(this);
              return false;
            }
          });

          $collection.each(function () {
            if (options.attribute(this) == val) {
              destElement = $(this);
              return false;
            }
          });
        } else {
          sourceElement = $source.filter(
            "[" +
              options.attribute +
              "=" +
              $(this).attr(options.attribute) +
              "]",
          );
          destElement = $collection.filter(
            "[" +
              options.attribute +
              "=" +
              $(this).attr(options.attribute) +
              "]",
          );
        }

        var animationOptions;
        if (sourceElement.length === 0) {
          // No such element in source collection...
          if (!options.useScaling) {
            animationOptions = {
              opacity: "1.0",
            };
          } else {
            animationOptions = {
              opacity: "1.0",
              scale: "1.0",
            };
          }
          // Let's create it
          d = destElement.clone();
          var rawDestElement = d.get(0);
          rawDestElement.style.position = "absolute";
          rawDestElement.style.margin = "0";
          rawDestElement.style.top =
            destElement.offset().top - correctionOffset.top + "px";
          rawDestElement.style.left =
            destElement.offset().left - correctionOffset.left + "px";
          d.css("opacity", 0.0); // IE
          if (options.useScaling) {
            d.css("transform", "scale(0.0)");
          }
          d.appendTo($sourceParent);

          animationQueue.push({ element: $(d), animation: animationOptions });
        }
      });

      $dest.remove();
      options.enhancement($sourceParent); // Perform custom visual enhancements during the animation
      for (i = 0; i < animationQueue.length; i++) {
        animationQueue[i].element.animate(
          animationQueue[i].animation,
          options.duration,
          options.easing,
          postCallback,
        );
      }
    });
  };
})(jQuery);
