// Hadoop Streaming mapper: total trade value per reporter country and product.
//
// Hadoop feeds us one CSV line at a time on stdin:
//     year,reporter_iso3,partner_iso3,hs2,flow,value_usd
//     2023,IND,CHN,85,M,44200000000
// and we print one "key <TAB> value" line per input line:
//     IND|85	44200000000
// Hadoop then sorts all mapper output by key, so every line for IND|85 reaches the
// same reducer one after another.

#include <iostream>
#include <string>

int main() {
    std::ios::sync_with_stdio(false);  // plain C++ streams are slow unless unhooked from C stdio
    std::string line;

    while (std::getline(std::cin, line)) {
        // find the 5 commas once instead of building a vector of fields for every line
        std::size_t c[5];
        std::size_t from = 0;
        bool ok = true;
        for (int i = 0; i < 5; ++i) {
            c[i] = line.find(',', from);
            if (c[i] == std::string::npos) { ok = false; break; }
            from = c[i] + 1;
        }
        if (!ok) continue;  // skip a malformed line instead of crashing the whole task

        std::string reporter = line.substr(c[0] + 1, c[1] - c[0] - 1);
        std::string hs2 = line.substr(c[2] + 1, c[3] - c[2] - 1);
        std::string value = line.substr(c[4] + 1);  // parsed by the reducer

        std::cout << reporter << '|' << hs2 << '\t' << value << '\n';
    }
    return 0;
}
