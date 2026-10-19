// Hadoop Streaming reducer: adds up the values for each key.
//
// Input arrives SORTED by key, e.g.
//     IND|85	44200000000
//     IND|85	4900000000
//     IND|87	...
// so a key is finished as soon as the next line has a different key - no hash map needed,
// memory use stays constant however big the input is.
//
// Summing is associative, so the same program also works as the combiner (a mini reducer that
// runs on each mapper's output before it is sent over the network).

#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <string>

int main() {
    std::ios::sync_with_stdio(false);
    std::cout << std::fixed << std::setprecision(2);

    std::string line, current;
    double sum = 0.0;
    bool have = false;

    while (std::getline(std::cin, line)) {
        std::size_t tab = line.find('\t');
        if (tab == std::string::npos) continue;

        std::string key = line.substr(0, tab);
        double value = std::strtod(line.c_str() + tab + 1, nullptr);  // also reads 1.2E10 style

        if (have && key != current) {
            std::cout << current << '\t' << sum << '\n';
            sum = 0.0;
        }
        current = key;
        sum += value;
        have = true;
    }
    if (have) std::cout << current << '\t' << sum << '\n';
    return 0;
}
