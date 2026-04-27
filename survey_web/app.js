            const safeFeel1 = getRadioValue("safeFeel1");
            const safeFeel2 = getRadioValue("safeFeel2");
            const safeFeel3 = getRadioValue("safeFeel3");
            const safeFeel4 = getRadioValue("safeFeel4");
            const safeFeel5 = getRadioValue("safeFeel5");

            function safeFeelScore(answer, reverse) {
              if (reverse) {
                if (answer === "매우 그렇다") return 0;
                if (answer === "그렇다") return 0.5;
                if (answer === "보통이다") return 1;
                if (answer === "그렇지 않다") return 1.5;
                if (answer === "매우 그렇지 않다") return 2;
                return 0;
              }

              if (answer === "매우 그렇지 않다") return 0;
              if (answer === "그렇지 않다") return 0.5;
              if (answer === "보통이다") return 1;
              if (answer === "그렇다") return 1.5;
              if (answer === "매우 그렇다") return 2;
              return 0;
            }

            const feltSafetyScore =
              safeFeelScore(safeFeel1, true) +
              safeFeelScore(safeFeel2, true) +
              safeFeelScore(safeFeel3, false) +
              safeFeelScore(safeFeel4, true) +
              safeFeelScore(safeFeel5, false);