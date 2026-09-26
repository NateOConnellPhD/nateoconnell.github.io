#!/usr/bin/ruby
# Adapt Nathaniel O'Connell's R double-helix normal-distribution design to SVG.
# The original R files and reference images stay in the private context folder.
# Geometry: dnorm(x, 0, 0.9) +/- 0.04 * sin(10 * x), sampled at 200 points.
# Output: one public vector asset, under 30 KB; no dependencies or caches.

require 'fileutils'

width = 420
height = 184
mean = 0.0
sd = 0.9
amplitude = 0.04
frequency = 10.0
baseline = 193.0
y_scale = 315.0
points = 200.times.map do |i|
  x = -4.2 + 8.4 * i / 199.0
  density = Math.exp(-0.5 * ((x - mean) / sd)**2) / (sd * Math.sqrt(2 * Math::PI))
  offset = amplitude * Math.sin(frequency * x)
  [20.0 + 400.0 * i / 199.0, baseline - y_scale * (density + offset),
   baseline - y_scale * (density - offset), baseline - y_scale * density]
end

coordinate = ->(value) { format('%.2f', value) }
strand = lambda do |column|
  points.each_with_index.map do |point, i|
    "#{i.zero? ? 'M' : 'L'}#{coordinate.call(point[0])},#{coordinate.call(point[column])}"
  end.join(' ')
end

# Keep the paired-base palette from the R design; use blue and green for strands.
pairs = [['#cd6600', '#8b0000'], ['#8b0000', '#cd6600'],
         ['#00008b', '#006400'], ['#006400', '#00008b']]
random = Random.new(42)
# Fewer rungs keep the small header mark from turning into a solid band.
rungs = points.each_slice(2).map do |sample|
  x, first, second, middle = sample.first
  start_color, end_color = pairs[random.rand(pairs.length)]
  %(<path d="M#{coordinate.call(x)},#{coordinate.call(first)} V#{coordinate.call(middle)}" stroke="#{start_color}"/>) +
    %(<path d="M#{coordinate.call(x)},#{coordinate.call(middle)} V#{coordinate.call(second)}" stroke="#{end_color}"/>)
end.join("\n    ")

svg = <<~SVG
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="10 30 #{width} #{height}" fill="none">
    <title>Double-helix normal distribution with a decision tree</title>
    <desc>Nathaniel O'Connell's normal-distribution helix design, adapted for his website.</desc>
    <g stroke-width="2" opacity="0.65">
      #{rungs}
    </g>
    <g stroke-width="4.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="#{strand.call(1)}" stroke="#408264"/>
      <path d="#{strand.call(2)}" stroke="#245a82"/>
    </g>
    <g stroke="#245a82" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M220 78 V112 M220 112 L186 150 M220 112 L254 150 M186 150 L164 187 M186 150 L208 187 M254 150 L232 187 M254 150 L276 187"/>
    </g>
    <g fill="#245a82">
      <circle cx="220" cy="112" r="5"/>
      <circle cx="186" cy="150" r="4.5"/>
      <circle cx="254" cy="150" r="4.5"/>
    </g>
    <g fill="#408264" stroke="#245a82" stroke-width="1.5">
      <circle cx="164" cy="187" r="4"/>
      <circle cx="208" cy="187" r="4"/>
      <circle cx="232" cy="187" r="4"/>
      <circle cx="276" cy="187" r="4"/>
    </g>
  </svg>
SVG

output = File.expand_path('../assets/images/normal-helix-logo.svg', __dir__)
FileUtils.mkdir_p(File.dirname(output))
File.write(output, svg)
puts "Wrote #{output} (#{svg.bytesize} bytes)"
